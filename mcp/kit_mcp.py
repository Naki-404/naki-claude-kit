"""Read-only MCP server (stdio, JSON-RPC 2.0) for projects that carry a `.claude/kit.json`.

Tools:
  kit_project_overview  - profile, git branch and change counts of the configured repos, key docs
  kit_verify_frozen     - sha256 of protected files against the frozen manifest
  kit_dataset_summary   - row counts and value counts of selected fields (never the text itself)
  kit_results           - list result files, or read one small text file inside a results folder

Standard library only. No network, no writes, no shell: git is called with a fixed argument list.
The project root is found by walking up from the working directory (or CLAUDE_PROJECT_DIR) to `.claude/kit.json`.
"""
from __future__ import annotations

import collections
import glob as globmod
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SERVER = {"name": "naki-kit", "version": "1.0.0"}
PROTOCOL = "2025-06-18"
MAX_READ = 200_000
TEXT_EXT = {".json", ".md", ".txt", ".csv", ".tsv", ".yaml", ".yml", ".log"}
ML_PROCS = r"python|ollama|llama|torch|vllm|lmstudio|comfy|stable"


def find_root() -> tuple[Path, dict]:
    for start in (os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()):
        if not start:
            continue
        d = Path(start).resolve()
        for p in (d, *d.parents):
            f = p / ".claude" / "kit.json"
            if f.is_file():
                return p, json.loads(f.read_text(encoding="utf-8"))
    raise RuntimeError("no .claude/kit.json found above the working directory")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def protected_files(root: Path, cfg: dict) -> list[Path]:
    out: set[Path] = set()
    for g in cfg.get("protected", {}).get("paths", []):
        out.update(Path(p) for p in globmod.glob(str(root / g), recursive=True) if Path(p).is_file())
    return sorted(out)


def write_manifest(root: Path, cfg: dict) -> Path:
    """Used by the installer (`install.py freeze`), not exposed as an MCP tool."""
    rel = cfg.get("mcp", {}).get("frozen_manifest", ".claude/kit-frozen.sha256")
    lines = [f"{sha256(p)}  {p.relative_to(root).as_posix()}" for p in protected_files(root, cfg)]
    target = root / rel
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=20)
    return r.stdout.strip() if r.returncode == 0 else ""


# ---------------------------------------------------------------------------------------------------------------
# tools


def tool_overview(root: Path, cfg: dict, _args: dict) -> dict:
    m = cfg.get("mcp", {})
    repos = []
    for r in m.get("repos", []):
        p = (root / r).resolve()
        if not (p / ".git").exists():
            repos.append({"path": r, "git": False})
            continue
        status = git(p, "status", "--porcelain=v1").splitlines()
        repos.append({
            "path": r,
            "branch": git(p, "rev-parse", "--abbrev-ref", "HEAD"),
            "last_commit": git(p, "log", "-1", "--format=%h %ad %s", "--date=short"),
            "modified": sum(1 for s in status if not s.startswith("??")),
            "untracked": sum(1 for s in status if s.startswith("??")),
            "ahead_behind": git(p, "rev-list", "--left-right", "--count", "@{upstream}...HEAD") or "no upstream",
        })
    docs = [{"path": d, "exists": (root / d).is_file()} for d in m.get("docs", [])]
    return {"root": str(root), "profile": cfg.get("profile"), "description": cfg.get("description"),
            "repos": repos, "docs": docs,
            "guards": {"protected_globs": cfg.get("protected", {}).get("paths", []),
                       "require_flags": [r.get("reason") for r in cfg.get("require_flags", [])],
                       "ask_commands": [r.get("reason") for r in cfg.get("ask_commands", [])]}}


def tool_verify_frozen(root: Path, cfg: dict, _args: dict) -> dict:
    rel = cfg.get("mcp", {}).get("frozen_manifest", ".claude/kit-frozen.sha256")
    mf = root / rel
    if not mf.is_file():
        return {"ok": False, "error": f"manifest {rel} missing; create it with: python install.py freeze <project>"}
    expected = {}
    for line in mf.read_text(encoding="utf-8").splitlines():
        if line.strip():
            h, _, path = line.partition("  ")
            expected[path] = h
    current = {p.relative_to(root).as_posix(): p for p in protected_files(root, cfg)}
    changed = [k for k, h in expected.items() if k in current and sha256(current[k]) != h]
    missing = [k for k in expected if k not in current]
    new = [k for k in current if k not in expected]
    return {"ok": not (changed or missing), "checked": len(expected), "changed": changed, "missing": missing,
            "new_unlisted": new, "manifest": rel,
            "manifest_date": datetime.fromtimestamp(mf.stat().st_mtime).isoformat(timespec="seconds")}


def tool_dataset_summary(root: Path, cfg: dict, args: dict) -> dict:
    ds = cfg.get("mcp", {}).get("datasets") or {}
    if not ds:
        return {"error": "no datasets configured in kit.json (mcp.datasets)"}
    fields = ds.get("fields", [])
    name = args.get("name")
    out = []
    for f in sorted(globmod.glob(str(root / ds["glob"]))):
        p = Path(f)
        if name and name not in p.name:
            continue
        counts = {k: collections.Counter() for k in fields}
        rows = bad = 0
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    bad += 1
                    continue
                rows += 1
                for k in fields:
                    v = r.get(k)
                    counts[k][v if isinstance(v, (str, int, bool)) or v is None else type(v).__name__] += 1
        out.append({"file": p.relative_to(root).as_posix(), "rows": rows, "bad_lines": bad,
                    "fields": {k: dict(c.most_common(20)) for k, c in counts.items() if c}})
    return {"datasets": out}


def results_roots(root: Path, cfg: dict) -> list[Path]:
    out = []
    for r in cfg.get("mcp", {}).get("results", []):
        out += [Path(p).resolve() for p in globmod.glob(str(root / r)) if Path(p).is_dir()]
    return sorted(set(out))


def tool_gpu_status(_root: Path, _cfg: dict, _args: dict) -> dict:
    try:
        q = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        apps = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"available": False, "error": type(e).__name__}
    if q.returncode != 0:
        return {"available": False}
    gpus = []
    for line in q.stdout.splitlines():
        name, util, used, total, temp = [x.strip() for x in line.split(",")]
        num = lambda s: round(float(s)) if s.replace(".", "", 1).isdigit() else None  # noqa: E731
        gpus.append({"name": name, "util_pct": num(util) or 0, "mem_used_mib": num(used) or 0,
                     "mem_total_mib": num(total) or 1, "temp_c": num(temp)})
    procs = []
    for line in apps.stdout.splitlines():
        parts = [x.strip() for x in line.split(",")]
        # on Windows every desktop app shows up with memory [N/A]; keep real compute users
        if len(parts) == 3 and (parts[2].isdigit() or re.search(ML_PROCS, parts[1], re.I)):
            procs.append({"pid": parts[0], "process": Path(parts[1]).name, "mem_mib": parts[2]})
    busy = any(g["util_pct"] > 20 or g["mem_used_mib"] > 0.5 * g["mem_total_mib"] for g in gpus)
    return {"available": True, "gpus": gpus, "compute_processes": procs,
            "advice": "GPU looks busy: ask the user before starting GPU work" if busy else "GPU looks free, still ask before starting GPU work"}


def tool_status_log(root: Path, cfg: dict, args: dict) -> dict:
    rel = cfg.get("mcp", {}).get("status_log")
    if not rel or not (root / rel).is_file():
        return {"error": "no status log configured (mcp.status_log)"}
    text = (root / rel).read_text(encoding="utf-8", errors="replace")
    sections, cur = [], None
    for line in text.splitlines():
        if line.startswith("#"):
            cur = {"heading": line.lstrip("# ").strip(), "lines": []}
            sections.append(cur)
        elif cur is not None:
            cur["lines"].append(line)
    n = int(args.get("sections", 3))
    pick = sections[-n:] if args.get("from_end", True) else sections[:n]
    body = "\n\n".join(f"## {s['heading']}\n" + "\n".join(s["lines"]).strip() for s in pick)
    return {"file": rel, "total_sections": len(sections), "headings": [s["heading"] for s in sections][-40:],
            "content": body[:MAX_READ]}


def tool_run_costs(root: Path, cfg: dict, args: dict) -> dict:
    m = cfg.get("mcp", {})
    excl = m.get("cost_exclude", [])
    files = sorted({Path(p) for g in m.get("cost_files", []) for p in globmod.glob(str(root / g))
                    if not any(Path(p).match(e) for e in excl)})
    name = args.get("name")
    out = []
    for f in files:
        if name and name not in f.name:
            continue
        agg: dict = {}
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                k = f"{r.get('model')} / {r.get('condition')}"
                a = agg.setdefault(k, {"calls": 0, "usd": 0.0, "in_tokens": 0, "out_tokens": 0, "errors": collections.Counter()})
                a["calls"] += 1
                a["usd"] += float(r.get("cost_usd") or 0)
                a["in_tokens"] += int(r.get("input_tokens") or 0)
                a["out_tokens"] += int(r.get("output_tokens") or 0)
                if r.get("error_kind") or r.get("error"):
                    a["errors"][r.get("error_kind") or "error"] += 1
        groups = {k: {**v, "usd": round(v["usd"], 4), "errors": dict(v["errors"])} for k, v in sorted(agg.items())}
        out.append({"file": f.relative_to(root).as_posix(), "total_usd": round(sum(v["usd"] for v in agg.values()), 4),
                    "groups": groups})
    return {"files": out, "grand_total_usd": round(sum(x["total_usd"] for x in out), 4)}


def tool_results(root: Path, cfg: dict, args: dict) -> dict:
    roots = results_roots(root, cfg)
    path = args.get("path")
    if path:
        target = (root / path).resolve()
        if not any(target == r or r in target.parents for r in roots):
            return {"error": "path is outside the configured results folders"}
        if not target.is_file() or target.suffix.lower() not in TEXT_EXT:
            return {"error": f"not a readable text file ({', '.join(sorted(TEXT_EXT))})"}
        data = target.read_bytes()[:MAX_READ].decode("utf-8", errors="replace")
        return {"path": target.relative_to(root).as_posix(), "size": target.stat().st_size,
                "truncated": target.stat().st_size > MAX_READ, "content": data}
    limit = int(args.get("limit", 30))
    files = []
    for r in roots:
        for p in r.rglob("*"):
            if p.is_file():
                st = p.stat()
                files.append((st.st_mtime, p.relative_to(root).as_posix(), st.st_size))
    files.sort(reverse=True)
    return {"roots": [r.relative_to(root).as_posix() for r in roots], "total": len(files),
            "latest": [{"path": f, "size": s, "modified": datetime.fromtimestamp(t).isoformat(timespec="seconds")}
                       for t, f, s in files[:limit]]}


TOOLS = {
    "kit_project_overview": (tool_overview, "Project profile, git branch and change counts of the configured repos, key docs and active guards.",
                             {"type": "object", "properties": {}}),
    "kit_verify_frozen": (tool_verify_frozen, "Check protected (frozen) files against their sha256 manifest. Run before and after work that touches research data.",
                          {"type": "object", "properties": {}}),
    "kit_dataset_summary": (tool_dataset_summary, "Row counts and value counts of configured fields for the dataset files. Never returns record text.",
                            {"type": "object", "properties": {"name": {"type": "string", "description": "substring of the file name, e.g. test_confirm"}}}),
    "kit_results": (tool_results, "List the newest files in the results folders, or read one small text file (json, md, csv, yaml, txt, log) inside them.",
                    {"type": "object", "properties": {"path": {"type": "string", "description": "file to read, relative to the project root"},
                                                      "limit": {"type": "integer", "description": "how many files to list (default 30)"}}}),
    "kit_gpu_status": (tool_gpu_status, "GPU load, memory and the processes holding it (nvidia-smi). Check before proposing GPU work.",
                       {"type": "object", "properties": {}}),
    "kit_status_log": (tool_status_log, "Latest sections of the project's running status log (plans), to pick up where work stopped.",
                       {"type": "object", "properties": {"sections": {"type": "integer", "description": "how many sections (default 3)"},
                                                         "from_end": {"type": "boolean", "description": "newest sections are at the end (default true)"}}}),
    "kit_run_costs": (tool_run_costs, "Calls, dollars, tokens and error kinds per model and condition from the prediction files of paid runs.",
                      {"type": "object", "properties": {"name": {"type": "string", "description": "substring of the file name, e.g. confirm"}}}),
}


# ---------------------------------------------------------------------------------------------------------------
# JSON-RPC loop


def handle(msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:  # notification
        return None
    if method == "initialize":
        result = {"protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
                  "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": s, "annotations": {"readOnlyHint": True}}
                            for n, (_, d, s) in TOOLS.items()]}
    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
        try:
            root, cfg = find_root()
            data = TOOLS[name][0](root, cfg, params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=1)}], "isError": False}
        except Exception as e:  # report, keep serving
            result = {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    stdin = sys.stdin.buffer
    out = sys.stdout.buffer
    for raw in stdin:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            resp = handle(msg)
        if resp is not None:
            out.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
            out.flush()


if __name__ == "__main__":
    main()
