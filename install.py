"""Installer for naki-claude-kit.

  python install.py user                         skills, agents, commands -> ~/.claude; hooks and MCP runtime ->
                                                 ~/.claude/naki-kit; guard hooks registered in ~/.claude/settings.json
  python install.py project <dir> --profile generic  .claude/kit.json, profile skills, .mcp.json, frozen manifest in <dir>
  python install.py codemap <dir>                optional Code Map of the code in codemap.dirs, served over MCP
  python install.py freeze <dir>                 rewrite the sha256 manifest of protected files after an approved change
  python install.py status [<dir>]               what is installed where
  python install.py uninstall user | uninstall project <dir>

Standard library only. Existing settings are merged, never replaced; every settings file is backed up first.
The guard hooks do nothing in a project without .claude/kit.json, so the user-level registration is safe.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

KIT = Path(__file__).resolve().parent
HOME = Path.home() / ".claude"
RUNTIME = HOME / "naki-kit"
RECORD = RUNTIME / "installed.json"
MARK = "naki-kit/hooks/kit_hooks.py"
MCP_NAME = "naki-kit"


def fwd(p: Path | str) -> str:
    return str(p).replace("\\", "/")


def backup(f: Path) -> None:
    if f.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(f, f.with_name(f"{f.name}.bak-{stamp}"))


def load_json(f: Path) -> dict:
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def save_json(f: Path, data: dict) -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------------
# hooks in settings.json


def hook_entries(python: str) -> dict:
    cmd = f'"{fwd(python)}" "{fwd(RUNTIME / "hooks" / "kit_hooks.py")}"'
    return {
        "PreToolUse": {"matcher": "Bash|PowerShell|Write|Edit|MultiEdit|NotebookEdit|Read|mcp__.*",
                       "hooks": [{"type": "command", "command": f"{cmd} pre", "timeout": 10,
                                  "statusMessage": "naki-kit: проверка правил проекта"}]},
        "PostToolUse": {"matcher": "Write|Edit|MultiEdit",
                        "hooks": [{"type": "command", "command": f"{cmd} post", "timeout": 40,
                                   "statusMessage": "naki-kit: линтер"}]},
        "Stop": {"hooks": [{"type": "command", "command": f"{cmd} stop", "timeout": 240,
                            "statusMessage": "naki-kit: проверка изменённых файлов"}]},
        "SessionStart": {"hooks": [{"type": "command", "command": f"{cmd} session", "timeout": 30}]},
    }


def strip_ours(hooks: dict) -> dict:
    """Remove kit hook groups, keep everything else exactly as it was."""
    out = {}
    for event, groups in hooks.items():
        kept = []
        for g in groups:
            inner = [h for h in g.get("hooks", [])
                     if MARK not in h.get("command", "").replace("\\", "/")]
            if inner:
                kept.append({**g, "hooks": inner})
        if kept:
            out[event] = kept
    return out


def register_hooks(settings_file: Path, python: str) -> None:
    s = load_json(settings_file)
    backup(settings_file)
    hooks = strip_ours(s.get("hooks", {}))
    for event, group in hook_entries(python).items():
        hooks.setdefault(event, []).append(group)
    s["hooks"] = hooks
    save_json(settings_file, s)


def unregister_hooks(settings_file: Path) -> None:
    if not settings_file.exists():
        return
    s = load_json(settings_file)
    backup(settings_file)
    hooks = strip_ours(s.get("hooks", {}))
    if hooks:
        s["hooks"] = hooks
    else:
        s.pop("hooks", None)
    save_json(settings_file, s)


# ---------------------------------------------------------------------------------------------------------------
# user scope


def copy_tree_items(src: Path, dst: Path, record: list[str]) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.iterdir()):
        target = dst / item.name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
        record.append(fwd(target.relative_to(HOME)))


def install_user(python: str) -> None:
    previous = load_json(RECORD).get("files", [])
    for rel in previous:  # files of an older kit version that no longer exist in this one
        p = HOME / rel
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    files: list[str] = []
    for kind in ("skills", "agents", "commands"):
        copy_tree_items(KIT / "kit" / kind, HOME / kind, files)
    for sub in ("hooks", "mcp", "tools"):
        if (RUNTIME / sub).exists():
            shutil.rmtree(RUNTIME / sub)
        shutil.copytree(KIT / sub, RUNTIME / sub, ignore=shutil.ignore_patterns("__pycache__"))
    register_hooks(HOME / "settings.json", python)
    save_json(RECORD, {"version": (KIT / "VERSION").read_text().strip(), "source": fwd(KIT), "python": fwd(python),
                       "installed": datetime.now().isoformat(timespec="seconds"), "files": files})
    print(f"user: {sum(f.startswith('skills/') for f in files)} skills, {sum(f.startswith('agents/') for f in files)} agents, "
          f"{sum(f.startswith('commands/') for f in files)} commands; runtime in {RUNTIME}; hooks in {HOME / 'settings.json'}")


def uninstall_user() -> None:
    for rel in load_json(RECORD).get("files", []):
        p = HOME / rel
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    unregister_hooks(HOME / "settings.json")
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    print("user scope removed (settings.json backed up)")


# ---------------------------------------------------------------------------------------------------------------
# project scope


def install_project(target: Path, profile: str, python: str, force: bool) -> None:
    prof = KIT / "profiles" / profile
    if not prof.is_dir():
        sys.exit(f"unknown profile {profile}; have: {', '.join(p.name for p in (KIT / 'profiles').iterdir())}")
    cdir = target / ".claude"
    cdir.mkdir(parents=True, exist_ok=True)
    cfg_file = cdir / "kit.json"
    if cfg_file.exists() and not force:
        print(f"kept existing {cfg_file} (use --force to replace it with the {profile} profile)")
    else:
        backup(cfg_file)
        shutil.copy2(prof / "kit.json", cfg_file)
    if (prof / "skills").is_dir():
        for s in (prof / "skills").iterdir():
            dst = cdir / "skills" / s.name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(s, dst)
    mcp_file = target / ".mcp.json"
    mcp = load_json(mcp_file)
    backup(mcp_file)
    mcp.setdefault("mcpServers", {})[MCP_NAME] = {"type": "stdio", "command": fwd(python),
                                                  "args": [fwd(RUNTIME / "mcp" / "kit_mcp.py")]}
    save_json(mcp_file, mcp)
    freeze(target)
    print(f"project {target}: profile {profile}, kit.json, skills, .mcp.json ({MCP_NAME}), frozen manifest")


CODEMAP_MCP = "naki-codemap"


def install_codemap(target: Path, python: str) -> None:
    """Code Map: build the map for the repos in kit.json `codemap.dirs` and register the naki-codemap MCP server."""
    import subprocess

    tool = RUNTIME / "tools" / "codemap.py"
    if not tool.is_file():
        sys.exit("run `python install.py user` first")
    cfg = load_json(target / ".claude" / "kit.json")
    dirs = (cfg.get("codemap") or {}).get("dirs") or ["."]
    for d in dirs:
        r = subprocess.run([python, str(tool), "build", str((target / d).resolve())], capture_output=True, text=True)
        print(f"Code Map {d}: {r.stdout.strip() or r.stderr.strip()[-300:]}")
    mcp_file = target / ".mcp.json"
    mcp = load_json(mcp_file)
    backup(mcp_file)
    servers = mcp.setdefault("mcpServers", {})
    for k in [k for k in servers if k.startswith(("graph-", "codemap-"))]:  # names used before v2
        servers.pop(k)
    servers[CODEMAP_MCP] = {"type": "stdio", "command": fwd(python), "args": [fwd(tool), "serve"]}
    save_json(mcp_file, mcp)
    print(f"MCP server {CODEMAP_MCP} registered in {mcp_file}")


def uninstall_project(target: Path) -> None:
    cdir = target / ".claude"
    for f in (cdir / "kit.json", cdir / "kit-frozen.sha256"):
        if f.exists():
            backup(f)
            f.unlink()
    for prof in (KIT / "profiles").iterdir():
        for s in (prof / "skills").glob("*") if (prof / "skills").is_dir() else []:
            if (cdir / "skills" / s.name).exists():
                shutil.rmtree(cdir / "skills" / s.name)
    mcp_file = target / ".mcp.json"
    if mcp_file.exists():
        backup(mcp_file)
        mcp = load_json(mcp_file)
        mcp.get("mcpServers", {}).pop(MCP_NAME, None)
        for k in [k for k in mcp.get("mcpServers", {}) if k.startswith(("graph-", "codemap-")) or k == CODEMAP_MCP]:
            mcp["mcpServers"].pop(k)
        if mcp.get("mcpServers"):
            save_json(mcp_file, mcp)
        else:
            mcp_file.unlink()
    print(f"project scope removed from {target}")


def freeze(target: Path) -> None:
    sys.path.insert(0, str(KIT / "mcp"))
    import kit_mcp  # noqa: E402

    cfg = load_json(target / ".claude" / "kit.json")
    if not cfg.get("protected", {}).get("paths"):
        return
    f = kit_mcp.write_manifest(target, cfg)
    n = sum(1 for line in f.read_text(encoding="utf-8").splitlines() if line.strip())
    print(f"frozen manifest: {n} files -> {f}")


def status(target: Path | None) -> None:
    rec = load_json(RECORD)
    print("user:", f"version {rec.get('version')}, {len(rec.get('files', []))} items, installed {rec.get('installed')}" if rec else "not installed")
    s = load_json(HOME / "settings.json")
    n = sum(MARK in h.get("command", "") for gs in s.get("hooks", {}).values() for g in gs for h in g.get("hooks", []))
    print("hooks registered in ~/.claude/settings.json:", n)
    if target:
        print("project kit.json:", (target / ".claude" / "kit.json").exists(),
              "| .mcp.json server:", MCP_NAME in load_json(target / ".mcp.json").get("mcpServers", {}),
              "| manifest:", (target / ".claude" / "kit-frozen.sha256").exists())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["user", "project", "codemap", "freeze", "status", "uninstall"])
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--profile", default="generic")
    ap.add_argument("--python", default=sys.executable, help="interpreter for hooks and MCP (default: this one)")
    ap.add_argument("--force", action="store_true", help="replace an existing .claude/kit.json")
    a = ap.parse_args()
    if a.action == "user":
        install_user(a.python)
    elif a.action == "project":
        if not a.rest:
            sys.exit("project needs a directory")
        install_project(Path(a.rest[0]).resolve(), a.profile, a.python, a.force)
    elif a.action == "codemap":
        install_codemap(Path(a.rest[0] if a.rest else ".").resolve(), a.python)
    elif a.action == "freeze":
        freeze(Path(a.rest[0] if a.rest else ".").resolve())
    elif a.action == "status":
        status(Path(a.rest[0]).resolve() if a.rest else None)
    elif a.action == "uninstall":
        if a.rest[:1] == ["user"]:
            uninstall_user()
        elif a.rest[:1] == ["project"] and len(a.rest) > 1:
            uninstall_project(Path(a.rest[1]).resolve())
        else:
            sys.exit("uninstall user | uninstall project <dir>")


if __name__ == "__main__":
    main()
