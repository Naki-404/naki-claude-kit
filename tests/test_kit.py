"""Tests for the guard hooks, the MCP server and the installer's settings merge. Run: python -m unittest -v"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
HOOK = KIT / "hooks" / "kit_hooks.py"
MCP = KIT / "mcp" / "kit_mcp.py"
FIXTURE = KIT / "tests" / "fixtures" / "example-kit.json"
sys.path.insert(0, str(KIT))
import install  # noqa: E402

# fake secrets are assembled at runtime so this file itself never contains one
FAKE_ANTHROPIC = "sk-" + "ant-" + "api03-" + "A" * 40
FAKE_GITHUB = "gh" + "p_" + "b" * 36
FAKE_PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"


class Project:
    def __init__(self, profile: str = "example") -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".claude").mkdir()
        src = FIXTURE if profile == "example" else KIT / "profiles" / profile / "kit.json"
        shutil.copy(src, self.root / ".claude" / "kit.json")
        ds = self.root / "app" / "research" / "dataset"
        ds.mkdir(parents=True)
        (ds / "test_confirm.jsonl").write_text('{"request_id":"a","gold":"incident","set":"confirm"}\n'
                                               '{"request_id":"b","gold":"benign","set":"confirm"}\n', encoding="utf-8")
        cfgdir = self.root / "app" / "research" / "experiment" / "config"
        cfgdir.mkdir(parents=True)
        (cfgdir / "cascade_policy.yaml").write_text("threshold: 0.5\n", encoding="utf-8")
        (self.root / "app" / "research" / "results").mkdir()
        (self.root / "app" / "research" / "results" / "summary.json").write_text('{"f1": 0.85}', encoding="utf-8")

        (self.root / "state").mkdir()

    def run(self, mode: str, event: dict) -> dict | None:
        env = {k: v for k, v in __import__("os").environ.items() if k != "CLAUDE_PROJECT_DIR"}
        env["KIT_STATE_DIR"] = str(self.root / "state")
        event.setdefault("cwd", str(self.root))
        event.setdefault("session_id", "test-session")
        r = subprocess.run([sys.executable, str(HOOK), mode], input=json.dumps(event).encode(), capture_output=True,
                           timeout=120, env=env)
        out = r.stdout.decode("utf-8").strip()
        assert r.returncode == 0, r.stderr
        return json.loads(out) if out else None

    def hook(self, tool: str, tool_input: dict, mode: str = "pre", cwd: Path | None = None) -> dict | None:
        return self.run(mode, {"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd or self.root)})

    def decision(self, tool: str, tool_input: dict, cwd: Path | None = None) -> str:
        out = self.hook(tool, tool_input, cwd=cwd)
        return out["hookSpecificOutput"].get("permissionDecision", "allow") if out else "allow"

    def context(self, tool: str, tool_input: dict) -> str:
        out = self.hook(tool, tool_input) or {}
        return out.get("hookSpecificOutput", {}).get("additionalContext", "")

    def set_cfg(self, **kv) -> None:
        f = self.root / ".claude" / "kit.json"
        cfg = json.loads(f.read_text(encoding="utf-8"))
        cfg.update(kv)
        f.write_text(json.dumps(cfg), encoding="utf-8")

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def cleanup(self) -> None:
        self.tmp.cleanup()


class HookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.p = Project()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.p.tmp.cleanup()

    def sh(self, cmd: str, cwd: Path | None = None) -> str:
        return self.p.decision("Bash", {"command": cmd}, cwd)

    # frozen files
    def test_write_to_frozen_dataset_denied(self) -> None:
        f = self.p.root / "app/research/dataset/test_confirm.jsonl"
        self.assertEqual(self.p.decision("Write", {"file_path": str(f), "content": "x"}), "deny")
        self.assertEqual(self.p.decision("Edit", {"file_path": str(f), "old_string": "a", "new_string": "b"}), "deny")

    def test_candidates_and_policy_frozen(self) -> None:
        c = self.p.root / "app/research/dataset/test_hard_315.candidates.jsonl"
        pol = self.p.root / "app/research/experiment/config/cascade_policy.yaml"
        self.assertEqual(self.p.decision("Write", {"file_path": str(c), "content": "x"}), "deny")
        self.assertEqual(self.p.decision("Edit", {"file_path": str(pol), "old_string": "0.5", "new_string": "0.6"}), "deny")

    def test_other_files_allowed(self) -> None:
        f = self.p.root / "app/research/dataset/train.jsonl"
        self.assertEqual(self.p.decision("Write", {"file_path": str(f), "content": "x"}), "allow")
        self.assertEqual(self.p.decision("Write", {"file_path": str(self.p.root / "design.md"), "content": "hi"}), "allow")

    def test_shell_change_of_frozen_file_asks(self) -> None:
        self.assertEqual(self.sh("rm app/research/dataset/test_confirm.jsonl"), "ask")
        ds = self.p.root / "app/research/dataset"
        self.assertEqual(self.sh("sed -i 's/a/b/' test_real.jsonl", cwd=ds), "ask")
        self.assertEqual(self.sh("echo x > research/dataset/test_285.jsonl", cwd=self.p.root / "app"), "ask")

    def test_shell_read_of_frozen_file_allowed(self) -> None:
        self.assertEqual(self.sh("wc -l app/research/dataset/test_confirm.jsonl"), "allow")
        self.assertEqual(self.sh("python -m research.experiment.evaluate_confirm"), "allow")

    # secrets
    def test_env_file_reads_denied(self) -> None:
        for cmd in ("cat .env", "type backend\\.env", "Get-Content .env.production", "grep KEY .env",
                    "python -c \"print(open('.env').read())\"", "head -5 app/.env"):
            self.assertEqual(self.sh(cmd), "deny", cmd)
        self.assertEqual(self.p.decision("Read", {"file_path": str(self.p.root / ".env")}), "deny")
        self.assertEqual(self.p.decision("Read", {"file_path": str(self.p.root / "keys" / "admin.pem")}), "deny")

    def test_env_example_allowed(self) -> None:
        self.assertEqual(self.sh("cat .env.example"), "allow")
        self.assertEqual(self.p.decision("Read", {"file_path": str(self.p.root / ".env.example")}), "allow")

    def test_env_dump_denied(self) -> None:
        for cmd in ("printenv", "env", "Get-ChildItem env:", "echo $ANTHROPIC_API_KEY", "Write-Host $env:OPENAI_API_KEY",
                    "python -c \"import os; print(os.environ)\""):
            self.assertEqual(self.sh(cmd), "deny", cmd)
        for cmd in ("env PYTHONIOENCODING=utf-8 python x.py", "echo $PATH", "python -c \"import os; os.environ.get('X')\""):
            self.assertEqual(self.sh(cmd), "allow", cmd)

    def test_git_add_env_denied(self) -> None:
        self.assertEqual(self.sh("git add .env"), "deny")
        self.assertEqual(self.sh("git add backend/app.py"), "allow")

    def test_secret_in_written_content_denied(self) -> None:
        f = str(self.p.root / "backend" / "config.py")
        for s in (FAKE_ANTHROPIC, FAKE_GITHUB, FAKE_PEM):
            out = self.p.hook("Write", {"file_path": f, "content": f"KEY = '{s}'"})
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertNotIn(s, out["hookSpecificOutput"]["permissionDecisionReason"])  # never echo the secret
        self.assertEqual(self.p.decision("Write", {"file_path": f, "content": "KEY = settings.anthropic_api_key"}), "allow")
        self.assertEqual(self.p.decision("MultiEdit", {"file_path": f, "edits": [{"old_string": "a", "new_string": FAKE_GITHUB}]}), "deny")

    # git
    def test_force_push_denied(self) -> None:
        for cmd in ("git push --force origin main", "git push -f", "git push origin +main", "git push --force-with-lease"):
            self.assertEqual(self.sh(cmd), "deny", cmd)
        self.assertEqual(self.sh("git push origin release-1.0"), "allow")
        self.assertEqual(self.sh("git push -u origin feature-x"), "allow")

    def test_skip_hooks_denied(self) -> None:
        self.assertEqual(self.sh("git commit --no-verify -m 'x'"), "deny")
        self.assertEqual(self.sh("git -c core.hooksPath=/dev/null commit -m x"), "deny")

    def test_attribution_follows_profile(self) -> None:
        cmd = "git commit -m 'fix\n\nCo-Authored-By: Claude <noreply@anthropic.com>'"
        self.assertEqual(self.sh(cmd), "allow")  # the example profile turns this rule off
        g = Project("generic")
        try:
            self.assertEqual(g.decision("Bash", {"command": cmd}), "deny")
        finally:
            g.tmp.cleanup()

    def test_destructive_git_asks(self) -> None:
        for cmd in ("git reset --hard HEAD~1", "git clean -fd", "git checkout -- .", "git branch -D old", "git stash drop"):
            self.assertEqual(self.sh(cmd), "ask", cmd)
        self.assertEqual(self.sh("git status"), "allow")

    def test_recursive_delete_asks(self) -> None:
        self.assertEqual(self.sh("rm -rf build"), "ask")
        self.assertEqual(self.p.decision("PowerShell", {"command": "Remove-Item -Recurse -Force dist"}), "ask")

    # paid runs and GPU
    def test_paid_run_needs_budget(self) -> None:
        self.assertEqual(self.sh("python -m research.experiment.execute --set confirm"), "deny")
        self.assertEqual(self.sh("python -m research.experiment.execute --set confirm --usd-budget 5"), "allow")
        self.assertEqual(self.sh("python research/run_experiment.py --dry-run"), "allow")

    def test_gpu_and_builders_ask(self) -> None:
        for cmd in ("python train_worker.py", "python programme.py programmes/confirm_real.json",
                    "ONLY_MODEL=r6a python run_local_tests.py", "ollama create mymodel -f Modelfile", "python build_hard.py", "python teacher.py"):
            self.assertEqual(self.sh(cmd), "ask", cmd)

    def test_reason_is_prefixed(self) -> None:
        out = self.p.hook("Bash", {"command": "git push -f"})
        self.assertTrue(out["hookSpecificOutput"]["permissionDecisionReason"].startswith("kit: "))

    def test_deny_wins_over_ask(self) -> None:
        self.assertEqual(self.sh("rm -rf x && cat .env"), "deny")


class ScopeTests(unittest.TestCase):
    def test_no_config_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            event = {"tool_name": "Bash", "tool_input": {"command": "git push -f"}, "cwd": d}
            env = {k: v for k, v in __import__("os").environ.items() if k != "CLAUDE_PROJECT_DIR"}
            r = subprocess.run([sys.executable, str(HOOK), "pre"], input=json.dumps(event).encode(), capture_output=True, env=env)
            self.assertEqual(r.stdout, b"")

    def test_subdirectory_finds_config(self) -> None:
        p = Project()
        try:
            sub = p.root / "app" / "research"
            self.assertEqual(p.decision("Bash", {"command": "git push -f"}, cwd=sub), "deny")
        finally:
            p.tmp.cleanup()

    def test_broken_config_fails_open(self) -> None:
        p = Project()
        try:
            (p.root / ".claude" / "kit.json").write_text("{broken", encoding="utf-8")
            self.assertEqual(p.decision("Bash", {"command": "git push -f"}), "allow")
        finally:
            p.tmp.cleanup()

    def test_disabled_config(self) -> None:
        p = Project()
        try:
            cfg = json.loads((p.root / ".claude" / "kit.json").read_text(encoding="utf-8"))
            cfg["enabled"] = False
            (p.root / ".claude" / "kit.json").write_text(json.dumps(cfg), encoding="utf-8")
            self.assertEqual(p.decision("Bash", {"command": "git push -f"}), "allow")
        finally:
            p.tmp.cleanup()


class PostHookTests(unittest.TestCase):
    def test_post_reports_linter_failure(self) -> None:
        p = Project()
        try:
            cfg = json.loads((p.root / ".claude" / "kit.json").read_text(encoding="utf-8"))
            cfg["post_edit"] = [{"name": "fake-lint", "paths": ["src/*.py"], "cmd": ["lint.cmd" if sys.platform == "win32" else "lint.sh", "{file}"]}]
            (p.root / ".claude" / "kit.json").write_text(json.dumps(cfg), encoding="utf-8")
            if sys.platform == "win32":
                (p.root / "lint.cmd").write_text("@echo E501 line too long & exit /b 1\r\n", encoding="utf-8")
            else:
                (p.root / "lint.sh").write_text("#!/bin/sh\necho E501 line too long; exit 1\n", encoding="utf-8")
                (p.root / "lint.sh").chmod(0o755)
            (p.root / "src").mkdir()
            (p.root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
            out = p.hook("Edit", {"file_path": str(p.root / "src" / "a.py")}, mode="post")
            self.assertEqual(out["decision"], "block")
            self.assertIn("E501", out["reason"])
            self.assertIsNone(p.hook("Edit", {"file_path": str(p.root / "README.md")}, mode="post"))
        finally:
            p.tmp.cleanup()

    def test_post_missing_linter_is_silent(self) -> None:
        p = Project()
        try:
            f = p.root / "app" / "backend" / "app.py"
            self.assertIsNone(p.hook("Write", {"file_path": str(f)}, mode="post"))
        finally:
            p.tmp.cleanup()


class McpTests(unittest.TestCase):
    def rpc(self, root: Path, messages: list[dict]) -> list[dict]:
        env = {k: v for k, v in __import__("os").environ.items() if k != "CLAUDE_PROJECT_DIR"}
        data = "".join(json.dumps(m) + "\n" for m in messages).encode()
        r = subprocess.run([sys.executable, str(MCP)], input=data, capture_output=True, cwd=root, env=env, timeout=30)
        return [json.loads(x) for x in r.stdout.decode("utf-8").splitlines() if x.strip()]

    def call(self, root: Path, name: str, args: dict | None = None) -> dict:
        resp = self.rpc(root, [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}])
        return json.loads(resp[0]["result"]["content"][0]["text"])

    def test_handshake_and_list(self) -> None:
        p = Project()
        try:
            resp = self.rpc(p.root, [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "nope"},
            ])
            self.assertEqual(len(resp), 3)
            self.assertEqual(resp[0]["result"]["serverInfo"]["name"], "naki-kit")
            names = {t["name"] for t in resp[1]["result"]["tools"]}
            self.assertEqual(names, {"kit_project_overview", "kit_verify_frozen", "kit_dataset_summary", "kit_results", "kit_gpu_status", "kit_status_log", "kit_run_costs"})
            self.assertEqual(resp[2]["error"]["code"], -32601)
        finally:
            p.tmp.cleanup()

    def test_verify_frozen_detects_change(self) -> None:
        p = Project()
        try:
            self.assertFalse(self.call(p.root, "kit_verify_frozen")["ok"])  # no manifest yet
            install.freeze(p.root)
            r = self.call(p.root, "kit_verify_frozen")
            self.assertTrue(r["ok"])
            self.assertEqual(r["checked"], 2)
            (p.root / "app/research/experiment/config/cascade_policy.yaml").write_text("threshold: 0.9\n")
            r = self.call(p.root, "kit_verify_frozen")
            self.assertFalse(r["ok"])
            self.assertEqual(r["changed"], ["app/research/experiment/config/cascade_policy.yaml"])
        finally:
            p.tmp.cleanup()

    def test_dataset_summary_counts_without_text(self) -> None:
        p = Project()
        try:
            r = self.call(p.root, "kit_dataset_summary", {"name": "confirm"})
            d = r["datasets"][0]
            self.assertEqual(d["rows"], 2)
            self.assertEqual(d["fields"]["gold"], {"incident": 1, "benign": 1})
            self.assertNotIn("request_id", json.dumps(r))
        finally:
            p.tmp.cleanup()

    def test_results_list_read_and_traversal(self) -> None:
        p = Project()
        try:
            r = self.call(p.root, "kit_results")
            self.assertEqual(r["total"], 1)
            r = self.call(p.root, "kit_results", {"path": "app/research/results/summary.json"})
            self.assertIn("0.85", r["content"])
            r = self.call(p.root, "kit_results", {"path": ".claude/kit.json"})
            self.assertIn("outside", r["error"])
            r = self.call(p.root, "kit_results", {"path": "app/research/results/../../../.claude/kit.json"})
            self.assertIn("outside", r["error"])
        finally:
            p.tmp.cleanup()

    def test_overview(self) -> None:
        p = Project()
        try:
            r = self.call(p.root, "kit_project_overview")
            self.assertEqual(r["profile"], "example")
            self.assertTrue(r["guards"]["protected_globs"])
        finally:
            p.tmp.cleanup()


class SettingsMergeTests(unittest.TestCase):
    def test_existing_kit_hooks_are_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "settings.json"
            old = {"type": "command", "command": '"py" "C:/Users/x/.claude/naki-kit/hooks/kit_hooks.py" pre'}
            f.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [old]}]}}), encoding="utf-8")
            install.register_hooks(f, "python")
            cmds = [h["command"] for g in json.loads(f.read_text(encoding="utf-8"))["hooks"]["PreToolUse"] for h in g["hooks"]]
            self.assertEqual(len(cmds), 1)
            self.assertIn("naki-kit/hooks/kit_hooks.py", cmds[0])

    def test_merge_keeps_foreign_hooks_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "settings.json"
            foreign = {"matcher": "Bash|PowerShell", "hooks": [{"type": "command", "command": "node strip-coauthor.js"}]}
            f.write_text(json.dumps({"attribution": {"commit": ""}, "hooks": {"PreToolUse": [foreign]}}), encoding="utf-8")
            install.register_hooks(f, "python")
            install.register_hooks(f, "python")
            s = json.loads(f.read_text(encoding="utf-8"))
            self.assertEqual(s["attribution"], {"commit": ""})
            self.assertEqual(s["hooks"]["PreToolUse"][0], foreign)
            self.assertEqual(len(s["hooks"]["PreToolUse"]), 2)
            self.assertEqual(len(s["hooks"]["PostToolUse"]), 1)
            install.unregister_hooks(f)
            s = json.loads(f.read_text(encoding="utf-8"))
            self.assertEqual(s["hooks"], {"PreToolUse": [foreign]})


FAKE_LINT_FAIL = ("@echo LINT-FAILED %* & exit /b 1\r\n", "#!/bin/sh\necho LINT-FAILED \"$@\"; exit 1\n")


def fake_tool(root: Path, name: str) -> str:
    if sys.platform == "win32":
        (root / f"{name}.cmd").write_text(FAKE_LINT_FAIL[0], encoding="utf-8")
        return f"{name}.cmd"
    (root / f"{name}.sh").write_text(FAKE_LINT_FAIL[1], encoding="utf-8")
    (root / f"{name}.sh").chmod(0o755)
    return f"{name}.sh"


class NewPreRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.p = Project()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.p.cleanup()

    def test_dev_server_needs_background(self) -> None:
        for cmd in ("npm run dev", "cd frontend && npm run dev", "uvicorn app.main:app --reload", "ollama serve",
                    "docker compose up", "npx vitest"):
            self.assertEqual(self.p.decision("Bash", {"command": cmd}), "deny", cmd)
        self.assertEqual(self.p.decision("Bash", {"command": "npm run dev", "run_in_background": True}), "allow")
        for cmd in ("docker compose up -d", "npm test", "npx vitest run", "npm run build"):
            self.assertEqual(self.p.decision("Bash", {"command": cmd}), "allow", cmd)

    def test_dev_server_rule_ignores_data_text(self) -> None:
        doc = "cat > notes.md <<'EOF'\nRun Vitest in watch mode with npm run dev\nEOF"
        self.assertEqual(self.p.decision("Bash", {"command": doc}), "allow")
        self.assertEqual(self.p.decision("Bash", {"command": "printf '{\"command\":\"npm run dev\"}' | python hook.py"}), "allow")
        self.assertEqual(self.p.decision("Bash", {"command": 'git commit -m "document npm run dev usage"'}), "allow")
        for cmd in ("PORT=3000 npm run dev", "cd web && npm run dev", "npm ci; npm run dev"):
            self.assertEqual(self.p.decision("Bash", {"command": cmd}), "deny", cmd)

    def test_push_and_install_warn_without_blocking(self) -> None:
        self.assertEqual(self.p.decision("Bash", {"command": "git push origin release-1.0"}), "allow")
        self.assertIn("push only if", self.p.context("Bash", {"command": "git push origin release-1.0"}))
        self.assertIn("dependency", self.p.context("Bash", {"command": "pip install requests"}))
        self.assertEqual(self.p.context("Bash", {"command": "pip install -r requirements.txt"}), "")

    def test_config_protection(self) -> None:
        cfg = self.p.root / "app" / "pyproject.toml"
        cfg.write_text("[tool.ruff]\n", encoding="utf-8")
        self.assertEqual(self.p.decision("Edit", {"file_path": str(cfg), "old_string": "a", "new_string": "b"}), "ask")
        ts = self.p.root / "app" / "frontend" / "tsconfig.app.json"
        self.assertEqual(self.p.decision("Write", {"file_path": str(ts), "content": "{}"}), "allow")  # new file

    def test_suppression_note(self) -> None:
        f = str(self.p.root / "backend" / "a.py")
        self.assertIn("suppression", self.p.context("Edit", {"file_path": f, "old_string": "x = 1", "new_string": "x = 1  # noqa: F841"}))
        self.assertEqual(self.p.context("Edit", {"file_path": f, "old_string": "y  # noqa", "new_string": "z  # noqa"}), "")

    def test_adhoc_docs(self) -> None:
        self.assertEqual(self.p.decision("Write", {"file_path": str(self.p.root / "app" / "SUMMARY.md"), "content": "x"}), "ask")
        self.assertEqual(self.p.decision("Write", {"file_path": str(self.p.root / "plans" / "NOTES.md"), "content": "x"}), "allow")
        self.assertEqual(self.p.decision("Write", {"file_path": str(self.p.root / "README.md"), "content": "x"}), "allow")


class McpGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.p = Project("generic")
        cls.p.set_cfg(mcp_rules=[
            {"tool": "^mcp__(?:prod|test)-db__execute_sql$", "field": "sql", "match": "sql_write", "decision": "ask", "reason": "write-SQL"},
            {"tool": "^mcp__(?:prod|test)-db__explain_query$", "field": "sql", "match": "sql_write", "when": {"analyze": True},
             "decision": "ask", "reason": "explain analyze runs the statement"},
            {"tool": "^mcp__warehouse__run_query$", "field": "query_text", "pattern": "\\bFROM\\s+events\\b",
             "unless": "\\bWHERE\\b", "decision": "ask", "reason": "full scan of a huge table"},
            {"tool": "^mcp__tracker__(?:update|close)_issue$", "decision": "deny", "reason": "tracker is read-only here"},
        ])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.p.cleanup()

    def sql(self, text: str, tool: str = "mcp__test-db__execute_sql") -> str:
        return self.p.decision(tool, {"sql": text})

    def test_reads_pass(self) -> None:
        for q in ("select * from deal where id = 1",
                  "SELECT id FROM deal FOR UPDATE",
                  "select 'update deal set x = 1' as t",
                  "-- delete from deal\nselect 1",
                  "with x as (select 1) select * from x",
                  "select updated_at, deleted from deal",
                  "explain select 1",
                  "select * from deal for no key update",
                  "select e'it\\'s; delete from t'",
                  'select "update", "delete" from t',
                  "select $$ delete from x $$"):
            self.assertEqual(self.sql(q), "allow", q)

    def test_writes_ask_with_the_keyword(self) -> None:
        for q in ("UPDATE deal SET status = 'X' WHERE id = 1",
                  "insert into deal(id) values (1)",
                  "delete from deal",
                  "with d as (delete from deal returning id) select * from d",
                  "select 1; drop table deal",
                  "select nextval('deal_seq')",
                  "select * into tmp_deal from deal",
                  "do $$ begin perform 1; end $$",
                  "truncate deal",
                  "with u as (update deal d set status = 'X' returning 1) select * from u",
                  'with u as (update "deal" set s = 1 returning 1) select 1',
                  "EXPLAIN ANALYZE UPDATE deal d SET status = 'X'",
                  "explain (analyze) select * into tmp_y from deal",
                  "explain analyze create table tmp_x as select * from deal",
                  "select E'\\'' ; delete from deal; --'",
                  "select pg_drop_replication_slot('debezium')",
                  "select pg_try_advisory_lock(1)",
                  "select lo_import('/tmp/x')"):
            self.assertEqual(self.sql(q), "ask", q)
        out = self.p.hook("mcp__prod-db__execute_sql", {"sql": "update deal set x = 1"})
        self.assertIn("write-SQL (UPDATE)", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_explain_only_with_analyze(self) -> None:
        self.assertEqual(self.p.decision("mcp__test-db__explain_query", {"sql": "delete from deal", "analyze": False}), "allow")
        self.assertEqual(self.p.decision("mcp__test-db__explain_query", {"sql": "delete from deal", "analyze": True}), "ask")

    def test_pattern_and_unless(self) -> None:
        tool = "mcp__warehouse__run_query"
        self.assertEqual(self.p.decision(tool, {"query_text": "SELECT * FROM events"}), "ask")
        self.assertEqual(self.p.decision(tool, {"query_text": "SELECT * FROM events WHERE day = :d"}), "allow")
        self.assertEqual(self.p.decision(tool, {"query_text": "SELECT * FROM users"}), "allow")

    def test_plain_deny_and_unrelated_tools(self) -> None:
        self.assertEqual(self.p.decision("mcp__tracker__close_issue", {"id": "PROJ-1"}), "deny")
        self.assertEqual(self.p.decision("mcp__tracker__get_issue", {"id": "PROJ-1"}), "allow")
        self.assertEqual(self.p.decision("mcp__other-db__execute_sql", {"sql": "delete from deal"}), "allow")

    def test_generic_profile_guards_any_sql_tool(self) -> None:
        p = Project("generic")
        try:
            self.assertEqual(p.decision("mcp__whatever__execute_sql", {"sql": "update t set a = 1"}), "ask")
            self.assertEqual(p.decision("mcp__whatever__query", {"query": "select 1"}), "allow")
        finally:
            p.cleanup()

    def test_matcher_covers_mcp(self) -> None:
        self.assertIn("mcp__.*", install.hook_entries(sys.executable)["PreToolUse"]["matcher"])


class CommitGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.p = Project()
        self.p.git("init", "-q")
        self.p.git("config", "user.email", "t@example.com")
        self.p.git("config", "user.name", "t")
        (self.p.root / "README.md").write_text("x\n", encoding="utf-8")
        self.p.git("add", "README.md")
        self.p.git("commit", "-qm", "init")

    def tearDown(self) -> None:
        self.p.cleanup()

    def commit(self) -> dict | None:
        return self.p.hook("Bash", {"command": "git commit -m 'change'"})

    def stage(self, name: str, text: str) -> None:
        f = self.p.root / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        self.p.git("add", "-f", name)

    def test_staged_env_denied(self) -> None:
        self.stage(".env", "A=1\n")
        self.assertEqual(self.commit()["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_staged_key_denied_without_echo(self) -> None:
        self.stage("app/config.py", f"KEY = '{FAKE_GITHUB}'\n")
        out = self.commit()["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertNotIn(FAKE_GITHUB, out["permissionDecisionReason"])

    def test_debug_code_noted(self) -> None:
        self.stage("web/app.ts", "console.log('x')\n")
        out = self.commit()["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", out)
        self.assertIn("console.log", out["additionalContext"])

    def test_big_file_asks(self) -> None:
        self.p.set_cfg(commit_gate={"enabled": True, "max_file_mb": 0, "checks": []})
        self.stage("data.bin", "x" * 2_000_000)
        self.assertEqual(self.commit()["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_failing_check_asks(self) -> None:
        tool = fake_tool(self.p.root, "lint")
        self.p.set_cfg(commit_gate={"enabled": True, "checks": [{"name": "lint", "paths": ["**/*.py"], "cmd": [tool, "{files}"]}]})
        self.stage("pkg/m.py", "x = 1\n")
        out = self.commit()["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "ask")
        self.assertIn("LINT-FAILED", out["permissionDecisionReason"])

    def test_clean_commit_only_reminder(self) -> None:
        self.stage("pkg/ok.py", "x = 1\n")
        out = self.commit()["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", out)


class StopAndSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.p = Project()

    def tearDown(self) -> None:
        self.p.cleanup()

    def test_stop_runs_batch_check_once(self) -> None:
        tool = fake_tool(self.p.root, "tsc")
        self.p.set_cfg(post_edit=[], stop_checks=[{"name": "tsc", "paths": ["src/**/*.ts"], "cmd": [tool, "{files}"]}])
        (self.p.root / "src").mkdir()
        for n in ("a.ts", "b.ts"):
            (self.p.root / "src" / n).write_text("let x = 1\n", encoding="utf-8")
            self.p.hook("Edit", {"file_path": str(self.p.root / "src" / n)}, mode="post")
        out = self.p.run("stop", {"stop_hook_active": False})
        self.assertEqual(out["decision"], "block")
        self.assertIn("LINT-FAILED", out["reason"])
        self.assertIn("a.ts", out["reason"])
        self.assertIn("b.ts", out["reason"])
        self.assertIsNone(self.p.run("stop", {}))  # state was consumed

    def test_stop_does_not_loop(self) -> None:
        tool = fake_tool(self.p.root, "tsc")
        self.p.set_cfg(stop_checks=[{"name": "tsc", "paths": ["**/*.ts"], "cmd": [tool]}])
        (self.p.root / "a.ts").write_text("x\n", encoding="utf-8")
        self.p.hook("Write", {"file_path": str(self.p.root / "a.ts")}, mode="post")
        out = self.p.run("stop", {"stop_hook_active": True})
        self.assertNotIn("decision", out)
        self.assertIn("LINT-FAILED", out["systemMessage"])

    def test_stop_flags_debug_code_in_new_file(self) -> None:
        (self.p.root / "x.py").write_text("def f():\n    breakpoint()\n", encoding="utf-8")
        self.p.hook("Write", {"file_path": str(self.p.root / "x.py")}, mode="post")
        out = self.p.run("stop", {})
        self.assertIn("breakpoint", out["reason"])

    def test_session_context_and_compact_rules(self) -> None:
        install.freeze(self.p.root)
        out = self.p.run("session", {"source": "startup"})["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        self.assertIn("frozen files intact", out["additionalContext"])
        self.assertNotIn("Rules that still apply", out["additionalContext"])
        (self.p.root / "app/research/experiment/config/cascade_policy.yaml").write_text("t: 1\n")
        out = self.p.run("session", {"source": "compact"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("FROZEN FILES CHANGED", out)
        self.assertIn("Rules that still apply", out)

    def test_glob_double_star_matches_zero_dirs(self) -> None:
        sys.path.insert(0, str(KIT / "hooks"))
        import kit_hooks
        self.assertTrue(kit_hooks.glob_match("a/backend/x.py", ["a/backend/**/*.py"]))
        self.assertTrue(kit_hooks.glob_match("a/backend/b/c/x.py", ["a/backend/**/*.py"]))
        self.assertFalse(kit_hooks.glob_match("a/frontend/x.py", ["a/backend/**/*.py"]))


class NewMcpToolTests(McpTests):
    def test_run_costs(self) -> None:
        p = Project()
        try:
            ex = p.root / "app/research/experiment"
            rows = [{"model": "opus", "condition": "C1", "cost_usd": 0.5, "input_tokens": 10, "output_tokens": 5},
                    {"model": "opus", "condition": "C1", "cost_usd": 0.25, "error_kind": "timeout"},
                    {"model": "rules", "condition": "C0", "cost_usd": 0.0}]
            (ex / "predictions_confirm.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            (ex / "predictions.bak.jsonl").write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
            r = self.call(p.root, "kit_run_costs")
            self.assertEqual(r["grand_total_usd"], 0.75)
            self.assertEqual(len(r["files"]), 1)
            self.assertEqual(r["files"][0]["groups"]["opus / C1"]["errors"], {"timeout": 1})
        finally:
            p.cleanup()

    def test_status_log(self) -> None:
        p = Project()
        try:
            (p.root / "plans").mkdir()
            (p.root / "plans" / "STATUS_2026-10-31.md").write_text("# A\nold\n## B\nmid\n## C\nnew\n", encoding="utf-8")
            r = self.call(p.root, "kit_status_log", {"sections": 1})
            self.assertEqual(r["total_sections"], 3)
            self.assertIn("new", r["content"])
            self.assertNotIn("old", r["content"])
        finally:
            p.cleanup()

    def test_gpu_status_shape(self) -> None:
        p = Project()
        try:
            r = self.call(p.root, "kit_gpu_status")
            self.assertIn("available", r)
        finally:
            p.cleanup()


if __name__ == "__main__":
    unittest.main()
