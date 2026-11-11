"""Guard hooks for Claude Code, driven by a per-project `.claude/kit.json`.

Usage (from settings.json):  python kit_hooks.py pre   (PreToolUse)
                             python kit_hooks.py post  (PostToolUse)

The script reads the hook event as JSON on stdin and finds the project config by walking up from the event's `cwd`
(or CLAUDE_PROJECT_DIR) to the first `.claude/kit.json`. Without a config it does nothing, so registering it at the
user level is harmless for other projects.

Design rules: standard library only, no network, no files written, no logging of commands or file contents.
Any internal error exits 0 without output, so a broken config never blocks work (it only stops guarding).
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

CONFIG_REL = Path(".claude") / "kit.json"
SHELL_TOOLS = {"Bash", "PowerShell"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
CASE_INSENSITIVE = os.name == "nt"

# ---------------------------------------------------------------------------------------------------------------
# config


def find_config(start: str | None) -> tuple[Path, dict] | None:
    candidates = [p for p in (start, os.environ.get("CLAUDE_PROJECT_DIR")) if p]
    for c in candidates:
        d = Path(c).resolve()
        for p in (d, *d.parents):
            f = p / CONFIG_REL
            if f.is_file():
                return p, json.loads(f.read_text(encoding="utf-8"))
    return None


# ---------------------------------------------------------------------------------------------------------------
# path helpers


def norm(s: str) -> str:
    s = s.replace("\\", "/")
    return s.lower() if CASE_INSENSITIVE else s


def rel_to_root(path: str, root: Path, cwd: str | None) -> str | None:
    """Path relative to the project root with forward slashes, or None when it lies outside the root."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(cwd or root) / p
    try:
        return norm(os.path.relpath(os.path.abspath(p), os.path.abspath(root)))
    except ValueError:  # another drive on Windows
        return None


def glob_match(rel: str, globs: list[str]) -> str | None:
    """First glob that matches a root-relative path. `**/` matches any depth, a glob without a slash matches names."""
    if rel is None or rel.startswith("../"):
        return None
    name = rel.rsplit("/", 1)[-1]
    for g in globs:
        gn = norm(g)
        if "/" not in gn:
            if fnmatch.fnmatchcase(name, gn):
                return g
        elif (fnmatch.fnmatchcase(rel, gn) or (gn.startswith("**/") and fnmatch.fnmatchcase(rel, gn[3:]))
              or ("/**/" in gn and fnmatch.fnmatchcase(rel, gn.replace("/**/", "/")))):  # ** also matches zero dirs
            return g
    return None


def tokens(cmd: str) -> list[str]:
    """Word-like pieces of a command: POSIX shlex split plus a split with Windows backslashes kept as separators."""
    parts: list[str] = []
    for text in (cmd, cmd.replace("\\", "/")):
        try:
            parts += shlex.split(text, posix=True)
        except ValueError:
            parts += text.split()
    out = []
    for t in parts:
        out.extend(x for x in re.split(r"[;|&<>()=,]+", t) if x)
    return list(dict.fromkeys(t.strip("'\"`") for t in out))


def command_paths(cmd: str, root: Path, cwd: str | None, globs: list[str]) -> list[str]:
    """Globs hit by any path-like token of a shell command."""
    hits = []
    for t in tokens(cmd):
        if not re.search(r"[\w*?]", t) or t.startswith("-"):
            continue
        rel = rel_to_root(t, root, cwd)
        g = glob_match(rel, globs) if rel else None
        if g is None and "/" not in norm(t):  # bare name typed in some other directory
            g = glob_match(norm(t), [x for x in globs if "/" not in x]) or glob_match("x/" + norm(t), globs)
        if g and g not in hits:
            hits.append(g)
    return hits


# ---------------------------------------------------------------------------------------------------------------
# rule data

SECRET_VALUE_PATTERNS = [
    ("Anthropic API key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("OpenAI-style API key", r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}"),
    ("GitHub token", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{50,}"),
    ("AWS access key id", r"\bAKIA[0-9A-Z]{16}\b"),
    ("Google API key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("Slack token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    ("private key block", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    ("Azure storage key", r"AccountKey=[A-Za-z0-9+/]{60,}={0,2}"),
]

READ_VERBS = (r"cat|type|more|less|head|tail|bat|nl|strings|xxd|od|base64|sort|uniq|awk|sed|grep|rg|findstr|"
              r"Get-Content|gc|Select-String|sls|Import-Csv|Format-Hex|cp|copy|Copy-Item|scp|curl|Invoke-WebRequest|"
              r"iwr|Invoke-RestMethod|irm|source|\.")
ENV_DUMP = [
    r"(?:^|[;&|]\s*)(?:printenv|env|set|export\s+-p|declare\s+-x)\s*(?:$|[;&|>])",
    r"\b(?:Get-ChildItem|gci|ls|dir|Get-Item)\s+env:",
    r"\[Environment\]::GetEnvironmentVariables",
    r"\b(?:print|dict|pprint|json\.dumps)\(\s*os\.environ\s*[,)]|\bos\.environ\.(?:items|values)\(",
    r"\b(?:console\.log|JSON\.stringify)\(\s*process\.env\s*[,)]",
]
ENV_SECRET_ECHO = r"(?:echo|Write-Output|Write-Host|print|printf)\b[^\n]*\$(?:env:)?\{?\w*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD)\w*"

FORCE_PUSH = r"\bgit\b[^\n;&|]*\bpush\b[^\n;&|]*(?:\s--force(?:-with-lease)?\b|\s-[A-Za-z]*f[A-Za-z]*\b|\s\+[\w./-]+)"
SKIP_HOOKS = r"\bgit\b[^\n;&|]*(?:--no-verify\b|--no-gpg-sign\b|-c\s+core\.hooksPath=|-c\s+commit\.gpgsign=false)"
AI_ATTRIBUTION = r"Co-Authored-By:|Generated with \[?Claude Code"
DESTRUCTIVE_GIT = [
    (r"\bgit\b[^\n;&|]*\breset\s+--hard\b", "git reset --hard drops uncommitted work"),
    (r"\bgit\b[^\n;&|]*\bclean\s+-[A-Za-z]*f", "git clean deletes untracked files"),
    (r"\bgit\b[^\n;&|]*\bcheckout\s+(?:--\s+)?\.(?:\s|$)", "git checkout . discards local changes"),
    (r"\bgit\b[^\n;&|]*\brestore\s+(?:--\S+\s+)*\.(?:\s|$)", "git restore . discards local changes"),
    (r"\bgit\b[^\n;&|]*\bbranch\s+-D\b", "git branch -D deletes an unmerged branch"),
    (r"\bgit\b[^\n;&|]*\bstash\s+(?:drop|clear)\b", "dropping a stash cannot be undone"),
    (r"\bgit\b[^\n;&|]*\bfilter-(?:branch|repo)\b", "history rewrite"),
]
RECURSIVE_DELETE = r"\brm\s+-[A-Za-z]*[rR][A-Za-z]*f|\brm\s+-[A-Za-z]*f[A-Za-z]*[rR]|\bRemove-Item\b[^\n;|]*-Recurse|\brmdir\s+/s|\brd\s+/s"
MUTATING = (r"(?:^|[\s;&|(])(?:rm|mv|cp|del|erase|ren|move|copy|truncate|tee|touch|shred|Remove-Item|ri|Move-Item|mi|"
            r"Copy-Item|cpi|Rename-Item|rni|Set-Content|sc|Add-Content|ac|Clear-Content|clc|Out-File|New-Item)(?=\s)"
            r"|\bsed\s+(?:-\w*\s+)*-i|\bperl\s+-[A-Za-z]*i|>{1,2}|\.(?:write_text|write_bytes|to_csv|to_json|dump)\(|"
            r"\bopen\([^)]*['\"][wa]b?\+?['\"]")


# ---------------------------------------------------------------------------------------------------------------
# decisions


class Verdict:
    def __init__(self) -> None:
        self.deny: list[str] = []
        self.ask: list[str] = []
        self.context: list[str] = []  # allowed, but Claude gets a note

    def output(self) -> dict | None:
        hso: dict = {"hookEventName": "PreToolUse"}
        if self.deny:
            hso |= {"permissionDecision": "deny", "permissionDecisionReason": "kit: " + " | ".join(self.deny)}
        elif self.ask:
            hso |= {"permissionDecision": "ask", "permissionDecisionReason": "kit: " + " | ".join(self.ask)}
        if self.context:
            hso["additionalContext"] = "kit: " + " | ".join(dict.fromkeys(self.context))
        return {"hookSpecificOutput": hso} if len(hso) > 1 else None


def search(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I | re.M) is not None


def check_shell(cmd: str, cfg: dict, root: Path, cwd: str | None, v: Verdict) -> None:
    sec = cfg.get("secrets", {})
    if sec.get("enabled", True):
        secret_files = sec.get("files", [])
        allowed = sec.get("allow_files", [])
        hits = [g for g in command_paths(cmd, root, cwd, secret_files)]
        for t in tokens(cmd):
            if glob_match(norm(t).rsplit("/", 1)[-1], allowed):
                hits = [h for h in hits if not glob_match(norm(t).rsplit("/", 1)[-1], [h])]
        if hits and search(rf"(?:^|[\s;&|(]){'(?:' + READ_VERBS + ')'}(?=\s)|<\s*\S|\bopen\(", cmd):
            v.deny.append(f"reading a secret file ({', '.join(hits)}) would print credentials; use the app's settings loader instead")
        if hits and search(r"\bgit\b[^\n;&|]*\badd\b", cmd):
            v.deny.append(f"secret file ({', '.join(hits)}) must not be staged in git")
        if any(search(p, cmd) for p in ENV_DUMP) or search(ENV_SECRET_ECHO, cmd):
            v.deny.append("dumping environment variables would print credentials")

    git = cfg.get("git", {})
    if git.get("block_force_push", True) and search(FORCE_PUSH, cmd):
        v.deny.append("force-push is not allowed; push normally or ask the user")
    if git.get("block_skip_hooks", True) and search(SKIP_HOOKS, cmd):
        v.deny.append("skipping git hooks or signing is not allowed; fix the hook failure instead")
    if git.get("block_ai_attribution", True) and search(r"\b(?:git|gh)\b", cmd) and search(AI_ATTRIBUTION, cmd):
        v.deny.append("remove Co-Authored-By / 'Generated with Claude Code' lines; commits use plain messages")
    if git.get("ask_destructive", True):
        for pat, why in DESTRUCTIVE_GIT:
            if search(pat, cmd):
                v.ask.append(why)
    if cfg.get("ask_recursive_delete", True) and search(RECURSIVE_DELETE, cmd):
        v.ask.append("recursive delete")

    for rule in cfg.get("require_flags", []):
        if search(rule["pattern"], cmd) and not any(f in cmd for f in rule["any_of"]):
            v.deny.append(rule.get("reason", f"command needs one of {rule['any_of']}"))


    for rule in cfg.get("ask_commands", []):
        if search(rule["pattern"], cmd):
            v.ask.append(rule.get("reason", "confirm this command"))

    for rule in cfg.get("warn_commands", []):
        if search(rule["pattern"], cmd):
            v.context.append(rule["message"])

    prot = cfg.get("protected", {})
    globs = prot.get("paths", [])
    if globs:
        hits = command_paths(cmd, root, cwd, globs)
        if hits and search(MUTATING, cmd):
            v.ask.append(f"command may change frozen files ({', '.join(hits)}); {prot.get('reason', 'they are protected')}")


HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\s*(?:\n|$)", re.S)
SEGMENT_SPLIT = re.compile(r"&&|\|\||[;|&\n]")
ENV_PREFIX = re.compile(r"^(?:\s*[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+")


def command_segments(cmd: str) -> list[str]:
    """The commands a shell line actually runs: heredoc bodies and quoted text removed, split on ; && || | &,
    leading VAR=value assignments dropped. Text that is only data (a document written by cat <<EOF, a JSON
    string) can no longer look like a command."""
    text = HEREDOC.sub("\n", cmd)
    text = re.sub(r"'[^']*'", "''", text)
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    segments = []
    for seg in SEGMENT_SPLIT.split(text):
        seg = ENV_PREFIX.sub("", seg.strip())
        if seg:
            segments.append(seg)
    return segments


def check_long_running(ti: dict, cfg: dict, v: Verdict) -> None:
    """A dev server in the foreground blocks the session until the tool times out."""
    if ti.get("run_in_background"):
        return
    segments = command_segments(ti.get("command", "") or "")
    for rule in cfg.get("long_running", []):
        if any(search(rule["pattern"], seg) for seg in segments):
            v.deny.append(f"'{rule.get('name', 'this command')}' never exits in the foreground: run it with "
                          f"run_in_background=true{rule.get('hint', '')}")
            return


# ---------------------------------------------------------------------------------------------------------------
# git helpers (fixed argument lists, no shell)


def git_out(repo: str, *args: str, timeout: int = 20) -> str:
    try:
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout if r.returncode == 0 else ""


def command_repo(cmd: str, cwd: str | None, root: Path) -> str:
    m = re.search(r"\bgit\s+-C\s+(\"[^\"]+\"|'[^']+'|\S+)", cmd) or re.match(r"\s*cd\s+(\"[^\"]+\"|'[^']+'|\S+)\s*&&", cmd)
    base = Path(cwd or root)
    if m:
        p = Path(m.group(1).strip("'\""))
        base = p if p.is_absolute() else base / p
    return str(base)


def added_lines(diff: str) -> list[tuple[str, str]]:
    """(file, line) for every added line of a unified diff."""
    out, current = [], ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("+") and not line.startswith("+++"):
            out.append((current, line[1:]))
    return out


def debug_leftovers(lines: list[tuple[str, str]], cfg: dict) -> list[str]:
    rules = cfg.get("debug_patterns", {})
    found = []
    for f, line in lines:
        s = line.strip()
        if s.startswith(("#", "//", "*")):
            continue
        ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
        for pat in rules.get(ext, []):
            if re.search(pat, line):
                found.append(f"{f}: {s[:80]}")
                break
    return found


def run_check(rule: dict, root: Path, files: list[Path]) -> str | None:
    """Run one configured checker; return its output when it fails, None when it passes or cannot run."""
    exe = root / rule["cmd"][0]
    if not exe.is_file():
        return None
    cwd = root / rule.get("cwd", ".")
    args = [str(exe)]
    for a in rule["cmd"][1:]:
        if a == "{files}":
            args += [os.path.relpath(f, cwd) for f in files]
        elif "{file}" in a:
            args += [a.replace("{file}", str(f)) for f in files[:1]]
        else:
            args.append(a)
    try:
        r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=rule.get("timeout", 60))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None if r.returncode == 0 else (r.stdout + r.stderr).strip()[:2500]


def check_commit(cmd: str, cfg: dict, root: Path, cwd: str | None, v: Verdict) -> None:
    """Look at what a `git commit` is about to record: secrets, frozen files, big files, debug code, lint."""
    cc = cfg.get("commit_gate", {})
    if not cc.get("enabled", True) or not search(r"\bgit\b(?:\s+-C\s+\S+)?[^\n;&|]*\bcommit\b", cmd):
        return
    repo = command_repo(cmd, cwd, root)
    top = git_out(repo, "rev-parse", "--show-toplevel").strip()
    if not top:
        return
    all_mode = search(r"\bcommit\b[^\n;&|]*\s(?:-(?!-)[A-Za-z]*a[A-Za-z]*\b|--all\b)", cmd)
    names = set(git_out(top, "diff", "--cached", "--name-only", "--diff-filter=ACMR").split())
    diff = git_out(top, "diff", "--cached", "-U0", "--no-color", "--diff-filter=ACMR")
    if all_mode:
        names |= set(git_out(top, "diff", "--name-only", "--diff-filter=ACMR").split())
        diff += git_out(top, "diff", "-U0", "--no-color", "--diff-filter=ACMR")
    if not names:
        return
    files = [Path(top) / n for n in sorted(names)]
    sec = cfg.get("secrets", {})
    staged_secrets = [n for n in names if glob_match(norm(n).rsplit("/", 1)[-1], sec.get("files", []))
                      and not glob_match(norm(n).rsplit("/", 1)[-1], sec.get("allow_files", []))]
    if staged_secrets:
        v.deny.append(f"secret files are staged: {', '.join(staged_secrets)}; unstage them (git restore --staged)")
    lines = added_lines(diff)
    leaks = sorted({f for f, line in lines for label, pat in SECRET_VALUE_PATTERNS if re.search(pat, line)})
    if leaks:
        v.deny.append(f"staged changes contain what looks like a key or token in: {', '.join(leaks)}")
    frozen = [n for n in names if rel_to_root(str(Path(top) / n), root, None) and
              glob_match(rel_to_root(str(Path(top) / n), root, None), cfg.get("protected", {}).get("paths", []))]
    if frozen:
        v.ask.append(f"commit changes frozen files: {', '.join(frozen)}")
    limit = cc.get("max_file_mb", 5) * 1024 * 1024
    big = [f"{f.name} ({f.stat().st_size // 1048576} MB)" for f in files if f.is_file() and f.stat().st_size > limit]
    if big:
        v.ask.append(f"large files in the commit: {', '.join(big)}")
    leftovers = debug_leftovers(lines, cfg)
    if leftovers:
        v.context.append("debug code in the commit, remove it unless intended: " + "; ".join(leftovers[:8]))
    for rule in cc.get("checks", []):
        hit = [f for f in files if (r := rel_to_root(str(f), root, None)) and glob_match(r, rule["paths"]) and f.is_file()]
        if hit:
            out = run_check(rule, root, hit)
            if out:
                v.ask.append(f"{rule.get('name', 'check')} fails on staged files:\n{out[:1500]}")


def content_of(tool: str, ti: dict) -> str:
    if tool == "Write":
        return ti.get("content", "") or ""
    if tool == "Edit":
        return ti.get("new_string", "") or ""
    if tool == "MultiEdit":
        return "\n".join(e.get("new_string", "") or "" for e in ti.get("edits", []))
    if tool == "NotebookEdit":
        return ti.get("new_source", "") or ""
    return ""


def old_content_of(tool: str, ti: dict) -> str:
    if tool == "Edit":
        return ti.get("old_string", "") or ""
    if tool == "MultiEdit":
        return "\n".join(e.get("old_string", "") or "" for e in ti.get("edits", []))
    return ""


SUPPRESSIONS = r"#\s*noqa\b|eslint-disable|@ts-ignore|@ts-nocheck|#\s*type:\s*ignore|#\s*pragma:\s*no cover|pytest\.mark\.skip\b|\.skip\(|xit\("


def check_write(tool: str, ti: dict, cfg: dict, root: Path, cwd: str | None, v: Verdict) -> None:
    path = ti.get("file_path") or ti.get("notebook_path") or ""
    rel = rel_to_root(path, root, cwd) if path else None
    prot = cfg.get("protected", {})
    g = glob_match(rel, prot.get("paths", [])) if rel else None
    if g:
        v.deny.append(f"{rel} is frozen ({g}): {prot.get('reason', 'protected file')}. Ask the user to change it themselves")

    sec = cfg.get("secrets", {})
    text = content_of(tool, ti)
    name = norm(path).rsplit("/", 1)[-1]
    if sec.get("enabled", True):
        if glob_match(name, sec.get("files", [])) and not glob_match(name, sec.get("allow_files", [])):
            v.ask.append(f"writing a secret file ({name})")
        if not (rel and glob_match(rel, sec.get("scan_skip", []))):
            found = [label for label, pat in SECRET_VALUE_PATTERNS if re.search(pat, text)]
            if found:
                v.deny.append(f"the new content contains what looks like a {', '.join(found)}; keep secrets in .env, never in files")

    exists = bool(path) and Path(path if Path(path).is_absolute() else Path(cwd or root) / path).exists()
    gc = cfg.get("guarded_configs", {})
    if exists and rel and glob_match(rel, gc.get("paths", [])):
        v.ask.append(f"{rel} configures linters, types or tests; {gc.get('reason', 'fix the code instead of loosening the check')}")

    sup = cfg.get("suppressions", {})
    if sup.get("enabled", True) and Path(path).suffix.lower() in CODE_EXT:
        new = len(re.findall(SUPPRESSIONS, text, re.I)) - len(re.findall(SUPPRESSIONS, old_content_of(tool, ti), re.I))
        if new > 0:
            v.context.append(f"the edit adds {new} lint/type/test suppression(s); fix the cause unless suppressing is justified, and say why")

    docs = cfg.get("adhoc_docs", {})
    if tool == "Write" and not exists and docs.get("names") and re.fullmatch(docs["names"], name, re.I):
        if not (rel and glob_match(rel, docs.get("allowed", []))):
            v.ask.append(f"new ad-hoc document {name}: put notes in the conversation or in {', '.join(docs.get('allowed', [])) or 'docs/'} unless the user asked for this file")


def check_read(ti: dict, cfg: dict, root: Path, cwd: str | None, v: Verdict) -> None:
    sec = cfg.get("secrets", {})
    if not sec.get("enabled", True) or not sec.get("block_read_tool", True):
        return
    name = norm(ti.get("file_path", "")).rsplit("/", 1)[-1]
    if glob_match(name, sec.get("files", [])) and not glob_match(name, sec.get("allow_files", [])):
        v.deny.append(f"{name} holds credentials and must not be read into the conversation; read the settings code instead")


def pre(event: dict, root: Path, cfg: dict) -> dict | None:
    tool = event.get("tool_name", "")
    ti = event.get("tool_input") or {}
    cwd = event.get("cwd")
    v = Verdict()
    if tool in SHELL_TOOLS:
        cmd = ti.get("command", "") or ""
        check_shell(cmd, cfg, root, cwd, v)
        check_long_running(ti, cfg, v)
        if not v.deny:
            check_commit(cmd, cfg, root, cwd, v)
    elif tool in WRITE_TOOLS:
        check_write(tool, ti, cfg, root, cwd, v)
    elif tool == "Read":
        check_read(ti, cfg, root, cwd, v)
    elif tool.startswith("mcp__"):
        check_mcp(tool, ti, cfg, v)
    return v.output()


SQL_NOISE = re.compile(r"--[^\n]*|/\*.*?\*/|\$(\w*)\$.*?\$\1\$|(?<![\w])[eE]'(?:\\.|''|[^'\\])*'|'(?:''|[^'])*'", re.S)
SQL_QUOTED = re.compile(r'"(?:""|[^"])*"')
SQL_EXPLAIN = re.compile(r"^\s*EXPLAIN\b\s*(?:\([^)]*\)\s*|(?:ANALYZE|ANALYSE|VERBOSE|COSTS|BUFFERS|SETTINGS|WAL|TIMING|SUMMARY|FORMAT\s+\w+)\b\s*)*", re.I)
SQL_LEAD = re.compile(
    r"^\s*(?:\(\s*)*(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|GRANT|REVOKE|COPY|CALL|DO|VACUUM|REINDEX|"
    r"CLUSTER|COMMENT|LOCK|REFRESH|SECURITY|REASSIGN|IMPORT|EXECUTE|PREPARE|SET|RESET|DISCARD|LISTEN|NOTIFY|LOAD)\b", re.I)
SQL_NOT_WRITE = re.compile(r"\bFOR\s+(?:NO\s+KEY\s+)?UPDATE\b|\bFOR\s+(?:KEY\s+)?SHARE\b|\bON\s+(?:UPDATE|DELETE)\b", re.I)
SQL_INNER = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE)\b", re.I)
SQL_FUNCS = re.compile(
    r"\b(nextval|setval|set_config|lo_\w+|dblink\w*|pg_(?:terminate_backend|cancel_backend|reload_conf|\w*advisory\w*|"
    r"switch_wal|rotate_logfile|\w*replication_slot\w*|replication_origin_\w+|promote|stat_reset\w*|file_\w+|"
    r"wal_replay_\w+|import_system_collations|log_backend_memory_contexts|create_restore_point|backup_\w+))\s*\(", re.I)
SQL_SELECT_INTO = re.compile(r"^\s*(?:SELECT|WITH)\b(?:(?!\bFROM\b).)*\bINTO\b", re.I | re.S)


def sql_writes(sql: str) -> list[str]:
    text = SQL_QUOTED.sub(" q ", SQL_NOISE.sub(" ", sql or ""))
    found = []
    for stmt in text.split(";"):
        if not stmt.strip():
            continue
        stmt = SQL_EXPLAIN.sub("", stmt, count=1)
        lead = SQL_LEAD.match(stmt)
        if lead:
            found.append(lead.group(1).upper())
        found += [m.group(1).upper() for m in SQL_INNER.finditer(SQL_NOT_WRITE.sub(" ", stmt))]
        found += [m.group(1).lower() + "()" for m in SQL_FUNCS.finditer(stmt)]
        if SQL_SELECT_INTO.match(stmt):
            found.append("SELECT INTO")
    return list(dict.fromkeys(found))


def mcp_text(ti: dict, field: str | None) -> str:
    if field:
        val = ti.get(field)
        return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False) if val is not None else ""
    return "\n".join(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for v in ti.values())


def check_mcp(tool: str, ti: dict, cfg: dict, v: Verdict) -> None:
    for rule in cfg.get("mcp_rules", []):
        if not re.search(rule.get("tool", "$^"), tool):
            continue
        if any(ti.get(k) != want for k, want in (rule.get("when") or {}).items()):
            continue
        text = mcp_text(ti, rule.get("field"))
        detail = ""
        if rule.get("match") == "sql_write":
            hits = sql_writes(text)
            if not hits:
                continue
            detail = f" ({', '.join(hits)})"
        if rule.get("pattern") and not search(rule["pattern"], text):
            continue
        if rule.get("unless") and search(rule["unless"], text):
            continue
        reason = rule.get("reason", f"{tool} needs a look") + detail
        {"deny": v.deny, "ask": v.ask}.get(rule.get("decision", "ask"), v.context).append(reason)


# ---------------------------------------------------------------------------------------------------------------
# PostToolUse and Stop: per-edit lint, then one batch check of everything edited in the turn


def state_dir() -> Path:
    d = Path(os.environ.get("KIT_STATE_DIR") or Path(__file__).resolve().parent.parent / "state")
    d.mkdir(parents=True, exist_ok=True)
    return d


def edited_file(event: dict) -> Path:
    sid = re.sub(r"[^A-Za-z0-9_-]", "", str(event.get("session_id") or "nosession"))[:64]
    return state_dir() / f"{sid}.edited"


def post(event: dict, root: Path, cfg: dict) -> dict | None:
    """Remember the edited path for the Stop check and run fast per-file linters. Never rewrites the file."""
    tool = event.get("tool_name", "")
    if tool not in WRITE_TOOLS:
        return None
    ti = event.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path") or ""
    rel = rel_to_root(path, root, event.get("cwd")) if path else None
    if not rel or rel.startswith("../"):
        return None
    if cfg.get("stop_checks") or cfg.get("debug_patterns"):
        with edited_file(event).open("a", encoding="utf-8") as f:
            f.write(str(root / rel) + "\n")
    for rule in cfg.get("post_edit", []):
        if glob_match(rel, rule["paths"]):
            out = run_check(rule, root, [root / rel])
            if out:
                return {"decision": "block", "reason": f"kit: {rule.get('name', 'check')} found problems in {rel}:\n{out}"}
    return None


def codemap_cfg(cfg: dict) -> dict:
    return cfg.get("codemap") or {}


CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".cs", ".sql", ".ps1", ".sh"}


def refresh_codemaps(files: list[Path], root: Path, cfg: dict) -> None:
    """Rebuild the Code Map in the background for each mapped repo whose code changed in this turn."""
    g = codemap_cfg(cfg)
    tool = Path(__file__).resolve().parent.parent / "tools" / "codemap.py"
    if not g.get("auto_update", True) or not tool.is_file():
        return
    for d in g.get("dirs", []):
        repo = (root / d).resolve()
        if not (repo / ".codemap" / "codemap.json").is_file():
            continue
        if any(p.suffix.lower() in CODE_EXT and repo in p.resolve().parents for p in files):
            flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
            try:
                subprocess.Popen([sys.executable, str(tool), "build", str(repo)], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
                                 start_new_session=os.name != "nt")
            except OSError:
                pass


def stop(event: dict, root: Path, cfg: dict) -> dict | None:
    """At the end of a turn: type check, lint and debug-code scan over every file edited in it, in one pass."""
    f = edited_file(event)
    if not f.exists():
        return None
    files = sorted({Path(p) for p in f.read_text(encoding="utf-8").splitlines() if p.strip()})
    f.unlink()
    files = [p for p in files if p.is_file()]
    if not files:
        return None
    problems = []
    for rule in cfg.get("stop_checks", []):
        hit = [p for p in files if glob_match(rel_to_root(str(p), root, None), rule["paths"])]
        if hit:
            out = run_check(rule, root, hit)
            if out:
                problems.append(f"{rule.get('name', 'check')}:\n{out}")
    if cfg.get("debug_patterns"):
        lines: list[tuple[str, str]] = []
        for p in files:
            d = git_out(str(p.parent), "diff", "-U0", "--no-color", "HEAD", "--", p.name)
            if d:
                lines += [(p.name, line) for _, line in added_lines(d)]
            elif not git_out(str(p.parent), "ls-files", "--", p.name).strip():  # untracked: whole file is new
                lines += [(p.name, line) for line in p.read_text(encoding="utf-8", errors="replace").splitlines()]
        left = debug_leftovers(lines, cfg)
        if left:
            problems.append("debug code added in this turn:\n" + "\n".join(left[:15]))
    refresh_codemaps(files, root, cfg)
    if not problems:
        return None
    text = "kit: checks after this turn found problems; fix them or tell the user why not.\n\n" + "\n\n".join(problems)
    if event.get("stop_hook_active"):  # already continued once for this: report, do not loop
        return {"systemMessage": text[:1500]}
    return {"decision": "block", "reason": text[:5000]}


# ---------------------------------------------------------------------------------------------------------------
# SessionStart: local facts about the project, and the key rules again after a compaction


def gpu_line() -> str | None:
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return None
        util, used, total = [x.strip() for x in r.stdout.splitlines()[0].split(",")]
        apps = subprocess.run(["nvidia-smi", "--query-compute-apps=process_name,used_memory", "--format=csv,noheader"],
                              capture_output=True, text=True, timeout=10).stdout
        names = sorted({Path(a.split(",")[0].strip()).name for a in apps.splitlines()
                        if a.strip() and (a.split(",")[-1].strip().split()[0].isdigit()
                                          or re.search(r"python|ollama|llama|torch|vllm", a, re.I))})
        return f"GPU {util}% busy, {used}/{total} MiB used" + (f", compute processes: {', '.join(names)}" if names else "")
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def frozen_line(root: Path, cfg: dict) -> str | None:
    import glob as globmod
    import hashlib
    rel = cfg.get("mcp", {}).get("frozen_manifest", ".claude/kit-frozen.sha256")
    mf = root / rel
    if not mf.is_file():
        return None
    bad = []
    for line in mf.read_text(encoding="utf-8").splitlines():
        h, _, p = line.partition("  ")
        f = root / p
        if p and (not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != h):
            bad.append(p)
    listed = {line.partition("  ")[2] for line in mf.read_text(encoding="utf-8").splitlines()}
    new = [Path(x).relative_to(root).as_posix() for g in cfg.get("protected", {}).get("paths", [])
           for x in globmod.glob(str(root / g)) if Path(x).relative_to(root).as_posix() not in listed]
    if bad:
        return f"FROZEN FILES CHANGED: {', '.join(bad)}. Tell the user before doing anything else."
    return f"frozen files intact ({len(listed - {''})} checked)" + (f"; not in manifest yet: {', '.join(new)}" if new else "")


def session(event: dict, root: Path, cfg: dict) -> dict | None:
    sc = cfg.get("session_context", {})
    if not sc.get("enabled", True):
        return None
    lines = [f"kit profile '{cfg.get('profile')}' active for {root}"]
    for r in cfg.get("mcp", {}).get("repos", []):
        p = root / r
        if (p / ".git").exists():
            branch = git_out(str(p), "rev-parse", "--abbrev-ref", "HEAD").strip()
            status = git_out(str(p), "status", "--porcelain=v1").splitlines()
            lines.append(f"{r}: branch {branch}, {len(status)} uncommitted paths")
    if sc.get("frozen_check", True):
        fl = frozen_line(root, cfg)
        if fl:
            lines.append(fl)
    if sc.get("gpu", False):
        gl = gpu_line()
        if gl:
            lines.append(gl)
    maps = []
    for g in codemap_cfg(cfg).get("dirs", []):
        gj = root / g / ".codemap" / "codemap.json"
        if gj.is_file():
            behind = git_out(str(root / g), "rev-list", "--count", f"--since={int(gj.stat().st_mtime)}", "HEAD").strip()
            maps.append((g, int(behind) if behind.isdigit() else 0))
    if len(maps) == 1:
        g, behind = maps[0]
        lines.append(f"Code Map for {g} is ready (MCP naki-codemap: codemap_search, codemap_symbol, codemap_path, codemap_hubs); "
                     f"{behind} commits since it was built" + ("; refresh with /naki-codemap" if behind else ""))
    elif maps:
        stale = [f"{Path(g).name} ({b})" for g, b in maps if b]
        lines.append(f"Code Map ready for {len(maps)} repos, served as one linked map (MCP naki-codemap: codemap_search, "
                     "codemap_symbol, codemap_path, codemap_routes, codemap_data; repo=<folder> narrows to one)"
                     + (f"; commits since build: {', '.join(stale)}" if stale else ""))
    if event.get("source") == "compact" and sc.get("rules_after_compact"):
        lines.append("Rules that still apply after the compaction: " + " ".join(sc["rules_after_compact"]))
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(lines)}}


MODES = {"pre": pre, "post": post, "stop": stop, "session": session}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
        found = find_config(event.get("cwd"))
        if not found or mode not in MODES:
            return 0
        root, cfg = found
        if not cfg.get("enabled", True):
            return 0
        out = MODES[mode](event, root, cfg)
    except Exception:  # never break the session because of the guard itself
        return 0
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
