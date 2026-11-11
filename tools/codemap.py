"""Code Map: a structural map of repositories that Claude queries over MCP.

  python codemap.py build <repo> [--full]   build or refresh the map (only changed files are re-parsed)
  python codemap.py info <repo>             size and age of the map
  python codemap.py query <repo> <words>    search from the command line
  python codemap.py serve                   MCP server (stdio); repos come from .claude/kit.json `codemap.dirs`

What it maps: modules, classes, functions and methods with their location and signature; edges for imports, calls,
inheritance and implementations. Python is parsed with `ast`; TypeScript, JavaScript and Java with lightweight scanners.
Java also yields Spring routes, Feign clients, Kafka topics (placeholders resolved from application.properties/yml)
and jOOQ table reads and writes. With several repos the server serves one merged map in which frontend calls and Feign
clients reach the routes of other services and Kafka producers reach consumers. Standard library only, no network,
nothing leaves the machine. The map lives in `<repo>/.codemap/` and is excluded from git through `.git/info/exclude`.
"""
from __future__ import annotations

import ast
import bisect
import fnmatch
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path

VERSION = 8
OUT_DIR = ".codemap"
PY_EXT = {".py"}
JS_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
JAVA_EXT = {".java"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", "coverage", ".codemap",
             ".next", ".turbo", "playwright-report", "test-results", ".mypy_cache", ".ruff_cache", ".pytest_cache",
             "site-packages", ".idea", ".vscode", "target"}
DEFAULT_IGNORE = ["*.min.js", "*.d.ts", "*.bundle.js", "**/migrations/versions/*", "**/alembic/versions/*"]
MAX_FILE_BYTES = 600_000
CONFIG_NAME = re.compile(r"^(?:application|bootstrap)(?:-[\w.-]+)?\.(?:properties|ya?ml)$")
PATH_MARK = re.compile("\u27e8([^\u27e9]*)\u27e9")

# ---------------------------------------------------------------------------------------------------------------
# file discovery


def load_ignore(repo: Path) -> list[str]:
    pats = list(DEFAULT_IGNORE)
    f = repo / ".codemapignore"
    if f.is_file():
        pats += [line.strip() for line in f.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    return pats


def ignored(rel: str, pats: list[str]) -> bool:
    for p in pats:
        p = p.rstrip("/")
        if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p + "/*") or rel.startswith(p + "/") or fnmatch.fnmatch(Path(rel).name, p):
            return True
    return False


def discover(repo: Path) -> list[str]:
    pats = load_ignore(repo)
    out = []
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") or d in (".github",)]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in PY_EXT | JS_EXT | JAVA_EXT:
                continue
            full = Path(dirpath) / fn
            rel = full.relative_to(repo).as_posix()
            if ignored(rel, pats) or full.stat().st_size > MAX_FILE_BYTES:
                continue
            out.append(rel)
    return sorted(out)


def config_files(repo: Path) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") and d != "test"]
        out += [(Path(dirpath) / fn).relative_to(repo).as_posix() for fn in filenames if CONFIG_NAME.match(fn)]
    return sorted(out, key=lambda r: (re.match(r"^(?:application|bootstrap)\.", Path(r).name) is None, r))


def parse_properties(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s[0] in "#!":
            continue
        m = re.match(r"([^=:\s]+)\s*[=:]\s*(.*)$", s)
        if m:
            out.setdefault(m.group(1), m.group(2).strip())
    return out


def parse_yaml(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    stack: list[tuple[int, str]] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "-")) or s == "---":
            if s == "---":
                stack = []
            continue
        m = re.match(r"(\s*)([\w.\-\[\]@/]+)\s*:(?:\s+(.*))?$", line)
        if not m:
            continue
        indent = len(m.group(1))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        key = ".".join([k for _, k in stack] + [m.group(2)])
        val = (m.group(3) or "").strip()
        if val and not val.startswith(("#", "|", ">")):
            out.setdefault(key, re.sub(r"\s+#.*$", "", val).strip().strip("'\""))
        else:
            stack.append((indent, m.group(2)))
    return out


def load_props(repo: Path) -> dict[str, str]:
    props: dict[str, str] = {}
    for rel in config_files(repo):
        try:
            text = (repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for k, v in (parse_properties(text) if rel.endswith(".properties") else parse_yaml(text)).items():
            props.setdefault(k, v)
    return props


PLACEHOLDER = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")


def expand(value: str, props: dict[str, str], depth: int = 0) -> str:
    if depth > 6 or "${" not in value:
        return value

    def rep(m: re.Match) -> str:
        key, default = m.group(1).strip(), m.group(2)
        if key in props:
            return expand(props[key], props, depth + 1)
        return expand(default, props, depth + 1) if default is not None else m.group(0)

    return PLACEHOLDER.sub(rep, value)


# ---------------------------------------------------------------------------------------------------------------
# Python extraction


def py_module(rel: str) -> str:
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or rel


def py_signature(node: ast.AST) -> str:
    try:
        if isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            return f"class {node.name}({bases})" if bases else f"class {node.name}"
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"{prefix} {node.name}({ast.unparse(node.args)}){ret}"[:240]
    except Exception:  # ast.unparse can fail on unusual nodes; the name is enough then
        return getattr(node, "name", "")


def first_doc(node: ast.AST) -> str:
    doc = ast.get_docstring(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) else None
    return (doc or "").strip().split("\n")[0][:200]


def call_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = call_name(func.value)
        return f"{base}.{func.attr}" if base else f"?.{func.attr}"
    return None


HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
ROUTER_FACTORIES = {"APIRouter", "FastAPI", "Blueprint", "Flask", "Router"}


def const_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def router_prefixes(tree: ast.Module) -> dict[str, str]:
    """Module-level `router = APIRouter(prefix="/api/x")` (or url_prefix for Flask blueprints): name -> prefix."""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if fname in ROUTER_FACTORIES:
                prefix = next((const_str(k.value) for k in node.value.keywords if k.arg in ("prefix", "url_prefix")), "") or ""
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        out[t.id] = prefix
    return out


def route_decorators(fn: ast.AST, prefixes: dict[str, str]) -> list[tuple[str, str]]:
    """HTTP routes declared on a function: @router.get("/x"), @app.post(...), @router.api_route(path, methods=[...])."""
    out = []
    for dec in getattr(fn, "decorator_list", []):
        if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and isinstance(dec.func.value, ast.Name)):
            continue
        owner, attr = dec.func.value.id, dec.func.attr
        path = const_str(dec.args[0]) if dec.args else const_str(next((k.value for k in dec.keywords if k.arg == "path"), None))
        if path is None or (owner not in prefixes and attr not in HTTP_METHODS):
            continue
        if attr in HTTP_METHODS:
            methods = [attr.upper()]
        elif attr in ("api_route", "route"):
            kw = next((k.value for k in dec.keywords if k.arg == "methods"), None)
            methods = [const_str(e).upper() for e in getattr(kw, "elts", []) if const_str(e)] or ["GET"]
        else:
            continue
        out += [(m, prefixes.get(owner, "") + path) for m in methods]
    return out


def extract_python(rel: str, src: str) -> dict:
    mod = py_module(rel)
    lines = src.splitlines()
    tree = ast.parse(src)
    defs, refs, imports = [], [], {}

    def add_def(node, qname, kind, parent):
        defs.append({"id": qname, "kind": kind, "name": qname.rsplit(".", 1)[-1], "file": rel, "line": node.lineno,
                     "end": getattr(node, "end_lineno", node.lineno), "sig": py_signature(node) if kind != "module" else "",
                     "doc": first_doc(node), "parent": parent, "lang": "python"})

    defs.append({"id": mod, "kind": "module", "name": mod.rsplit(".", 1)[-1], "file": rel, "line": 1, "end": len(lines),
                 "sig": "", "doc": first_doc(tree), "parent": None, "lang": "python"})
    routes: list[dict] = []
    router_prefix = router_prefixes(tree)
    pkg = mod.rsplit(".", 1)[0] if "." in mod else ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imports[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
                refs.append({"src": mod, "kind": "imports", "target": a.name})
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = mod.split(".")
                anchor = anchor[: len(anchor) - node.level] if not rel.endswith("__init__.py") else anchor[: len(anchor) - node.level + 1]
                base = ".".join([*anchor, base] if base else anchor)
            for a in node.names:
                full = f"{base}.{a.name}" if base else a.name
                imports[a.asname or a.name] = full
                refs.append({"src": mod, "kind": "imports", "target": full, "alt": base})

    def visit(body, prefix, parent, cls=None):
        for node in body:
            if isinstance(node, ast.ClassDef):
                q = f"{prefix}.{node.name}"
                add_def(node, q, "class", parent)
                for b in node.bases:
                    n = call_name(b)
                    if n:
                        refs.append({"src": q, "kind": "inherits", "target": n, "scope": mod})
                visit(node.body, q, q, cls=q)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = f"{prefix}.{node.name}"
                add_def(node, q, "method" if cls else "function", parent)
                for method, path in route_decorators(node, router_prefix):
                    routes.append({"handler": q, "method": method, "path": path, "line": node.lineno})
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        n = call_name(sub.func)
                        if n:
                            refs.append({"src": q, "kind": "calls", "target": n, "scope": mod, "cls": cls})
                visit([n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))], q, q, cls)

    visit(tree.body, mod, mod)
    return {"lang": "python", "module": mod, "package": pkg, "defs": defs, "refs": refs, "imports": imports, "routes": routes}


# ---------------------------------------------------------------------------------------------------------------
# TypeScript / JavaScript extraction (lightweight scanner)

JS_DEF = re.compile(
    r"^[ \t]*(?:export\s+(?:default\s+)?)?(?:"
    r"(?:async\s+)?function\s*\*?\s*(?P<f>[A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\((?P<fa>[^)]*)\)"
    r"|class\s+(?P<c>[A-Za-z_$][\w$]*)(?:\s+extends\s+(?P<base>[A-Za-z_$][\w$.]*))?"
    r"|(?:const|let|var)\s+(?P<v>[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s+)?(?:\((?P<va>[^)]*)\)|[A-Za-z_$][\w$]*)\s*(?::[^=]+?)?=>"
    r"|(?:const|let|var)\s+(?P<v2>[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s+)?function\b"
    r"|(?:export\s+)?(?:interface|type)\s+(?P<t>[A-Za-z_$][\w$]*)"
    r")", re.M)
JS_METHOD = re.compile(r"^[ \t]+(?:public\s+|private\s+|protected\s+|static\s+|async\s+|readonly\s+)*(?P<m>[A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\([^)]*\)\s*(?::[^{]+)?\{", re.M)
JS_IMPORT = re.compile(r"""import\s+(?:type\s+)?(?P<what>[\s\S]*?)\s+from\s+['"](?P<src>[^'"]+)['"]|import\s+['"](?P<side>[^'"]+)['"]|require\(\s*['"](?P<req>[^'"]+)['"]\s*\)""")
JS_LAZY = re.compile(r"""(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:React\.)?lazy\(\s*\(\)\s*=>\s*import\(\s*['"](?P<src>[^'"]+)['"]""")
JS_HTTP = re.compile(
    r"""(?:(?<![\w$.])[A-Za-z_$][\w$]*(?:\(\s*\))?|\))\s*\.\s*(?P<m>get|post|put|patch|delete)\s*(?:<[^()]*?>)?\(\s*"""
    r"""(?:(?P<q>[`'"])(?P<path>[^`'"]*)(?P=q)|(?P<id>[A-Za-z_$][\w$]*)\s*(?:\+\s*(?P<q3>[`'"])(?P<tail>[^`'"]*)(?P=q3)\s*)?[,)])"""
    r"""|(?<![\w$.])fetch\(\s*(?P<q2>[`'"])(?P<path2>[^`'"]*)(?P=q2)(?P<rest>[^)]{0,200})""")
JS_CONST = re.compile(r"""(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::\s*string\s*)?=\s*([`'"])([^`'"]*)\2""")
JS_CALL = re.compile(r"(?<![\w$.])(?P<n>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*(?:<[^<>()]*>)?\s*\(")
JS_JSX = re.compile(r"<(?P<n>[A-Z][\w$]*)[\s/>]")
JS_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "typeof", "new", "await", "super", "import",
               "require", "console", "Promise", "Array", "Object", "String", "Number", "Boolean", "Math", "JSON", "Date", "Error",
               "Set", "Map", "parseInt", "parseFloat", "setTimeout", "clearTimeout", "useState", "useEffect", "useMemo",
               "useCallback", "useRef", "describe", "it", "test", "expect", "constructor"}


def strip_js(src: str) -> str:
    """Blank out comments and string contents while keeping offsets and line numbers."""
    out, i, n = list(src), 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out[i:j] = " " * (j - i)
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out[i:j] = [ch if ch == "\n" else " " for ch in src[i:j]]
            i = j
        elif c in "'\"`":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            for k in range(i + 1, min(j, n)):
                if out[k] != "\n":
                    out[k] = " "
            i = j + 1
        else:
            i += 1
    return "".join(out)


def block_end(clean: str, start: int) -> int:
    """Offset of the brace that closes the first block opened at or after `start` (or end of statement)."""
    i = clean.find("{", start)
    semi = clean.find(";", start)
    if i < 0 or (0 <= semi < i and "=>" not in clean[start:semi]):
        return semi if semi >= 0 else len(clean)
    depth = 0
    for j in range(i, len(clean)):
        if clean[j] == "{":
            depth += 1
        elif clean[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    return len(clean)


def js_module(rel: str) -> str:
    base = re.sub(r"\.(tsx?|jsx?|mjs|cjs)$", "", rel)
    return base[:-6] if base.endswith("/index") else base


def js_expand(raw: str, consts: dict[str, str]) -> tuple[str, str]:
    for _ in range(4):
        lead = re.match(r"^\$\{\s*([A-Za-z_$][\w$.]*)\s*\}", raw)
        if not lead:
            break
        if lead.group(1) not in consts:
            return raw[lead.end():], lead.group(1)
        raw = consts[lead.group(1)] + raw[lead.end():]
    return raw, ""


def extract_js(rel: str, src: str) -> dict:
    mod = js_module(rel)
    clean = strip_js(src)
    line_of = lambda off: clean.count("\n", 0, off) + 1  # noqa: E731
    lines = src.splitlines()
    defs = [{"id": mod, "kind": "module", "name": mod.rsplit("/", 1)[-1], "file": rel, "line": 1, "end": len(lines),
             "sig": "", "doc": "", "parent": None, "lang": "ts"}]
    refs, imports = [], {}
    for m in JS_IMPORT.finditer(src):
        target = m.group("src") or m.group("side") or m.group("req")
        what = m.group("what") or ""
        refs.append({"src": mod, "kind": "imports", "target": target})
        default_part, _, named_part = what.partition("{")
        default_name = default_part.strip().rstrip(",").strip()
        if re.fullmatch(r"[A-Za-z_$][\w$]*", default_name or "-"):
            imports[default_name] = f"{target}#default"
        names = re.findall(r"([A-Za-z_$][\w$]*)(?:\s+as\s+([A-Za-z_$][\w$]*))?", named_part.replace("}", " "))
        for orig, alias in names:
            if orig in ("type", "as"):
                continue
            imports[alias or orig] = f"{target}#{orig}"
    for m in JS_LAZY.finditer(src):  # const Page = lazy(() => import("./pages/Page"))
        refs.append({"src": mod, "kind": "imports", "target": m.group("src")})
        imports[m.group("name")] = f"{m.group('src')}#default"
    spans, headers, default_name = [], [], None
    m_def = re.search(r"^\s*export\s+default\s+([A-Za-z_$][\w$]*)\s*;?\s*$", clean, re.M)  # export default Name;
    for m in JS_DEF.finditer(clean):
        name = m.group("f") or m.group("c") or m.group("v") or m.group("v2") or m.group("t")
        if not name:
            continue
        kind = "class" if m.group("c") else "type" if m.group("t") else "function"
        start, line = m.start(), line_of(m.start())
        headers.append((m.start(), m.end()))
        end = block_end(clean, m.end()) if kind != "type" else m.end()
        q = f"{mod}#{name}"
        sig = re.sub(r"\s+", " ", lines[line - 1].strip())[:200] if line - 1 < len(lines) else name
        if re.match(r"\s*export\s+default\b", clean[m.start():m.end()]):
            default_name = q
        defs.append({"id": q, "kind": kind, "name": name, "file": rel, "line": line, "end": line_of(end), "sig": sig, "doc": "",
                     "parent": mod, "lang": "ts"})
        if m.group("base"):
            refs.append({"src": q, "kind": "inherits", "target": m.group("base")})
        if kind == "class":
            body = clean[m.end():end]
            for mm in JS_METHOD.finditer(body):
                mname = mm.group("m")
                if mname in JS_KEYWORDS:
                    continue
                moff = m.end() + mm.start()
                headers.append((moff, moff + len(mm.group(0))))
                mq = f"{q}.{mname}"
                mend = block_end(clean, moff + len(mm.group(0)) - 1)
                defs.append({"id": mq, "kind": "method", "name": mname, "file": rel, "line": line_of(moff), "end": line_of(mend),
                             "sig": re.sub(r"\s+", " ", mm.group(0).strip().rstrip("{"))[:200], "doc": "", "parent": q, "lang": "ts"})
                spans.append((mq, moff, mend))
        elif kind == "function":
            spans.append((q, m.end(), end))
    spans.sort(key=lambda s: s[2] - s[1])
    consts = {m.group(1): m.group(3) for m in JS_CONST.finditer(src) if clean[m.start()] == src[m.start()]}
    for m in JS_HTTP.finditer(src):
        if clean[m.start()] != src[m.start()]:
            continue
        method = (m.group("m") or "").upper()
        if not method:
            mm = re.search(r"""method\s*:\s*['"`](\w+)""", m.group("rest") or "")
            method = mm.group(1).upper() if mm else "GET"
        if m.group("id"):
            raw = "${" + m.group("id") + "}" + (m.group("tail") or "")
        else:
            raw = m.group("path") if m.group("path") is not None else m.group("path2") or ""
        path, base = js_expand(raw, consts)
        path = path.strip()
        if path.endswith("/") and re.match(r"\s*\+", src[m.end():m.end() + 20]):
            path += "{}"
        if path.startswith("/") or (base and not path):
            owner = next((q for q, a, b in spans if a <= m.start() <= b), mod)
            refs.append({"src": owner, "kind": "http", "method": method, "target": path, **({"base": base} if base else {})})
    for m in list(JS_CALL.finditer(clean)) + list(JS_JSX.finditer(clean)):
        name = m.group("n")
        if name.split(".")[0] in JS_KEYWORDS or any(a <= m.start() < b for a, b in headers):
            continue  # a keyword, or the name inside its own definition line
        owner = next((q for q, a, b in spans if a <= m.start() <= b), mod)
        refs.append({"src": owner, "kind": "calls", "target": name})
    if default_name is None and m_def and f"{mod}#{m_def.group(1)}" in {d["id"] for d in defs}:
        default_name = f"{mod}#{m_def.group(1)}"
    return {"lang": "ts", "module": mod, "package": mod.rsplit("/", 1)[0], "defs": defs, "refs": refs, "imports": imports,
            "default": default_name, "consts": consts}


JAVA_NOISE = re.compile(r'//[^\n]*|/\*.*?\*/|"""(?:\\.|(?!""").)*"""|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', re.S)
JAVA_TYPE = re.compile(r"(?<![\w$.])(?P<kw>@interface|class|interface|enum|record)\s+(?P<n>[A-Za-z_$][\w$]*)")
JAVA_MEMBER = re.compile(r"(?<![\w$.@])(?P<n>[A-Za-z_$][\w$]*)\s*\(")
JAVA_TAIL = re.compile(r"\s*(?:throws\s+[\w$.,\s]+?)?\s*(?P<e>[{;])|\s*default\b[^;{}]*;")
JAVA_FIELD = re.compile(r"(?<![\w$.@])(?P<t>[A-Za-z_$][\w$.]*(?:\s*<[^;{}()=]*>)?(?:\s*\[\s*\])*)\s+(?P<n>[A-Za-z_$][\w$]*)\s*(?=[=;,])")
JAVA_LOCAL = re.compile(r"(?<![\w$.])(?P<t>[A-Z][\w$]*(?:\.[A-Z][\w$]*)*(?:\s*<[^;{}()=]*?>)?(?:\s*\[\s*\])*)\s+(?P<n>[a-z_$][\w$]*)\s*(?=[=;:,)])")
JAVA_VAR = re.compile(r"\bvar\s+(?P<n>[A-Za-z_$][\w$]*)\s*=\s*new\s+(?P<t>[A-Z][\w$.]*)")
JAVA_QCALL = re.compile(r"(?:(?<=\bthis\.)|(?<![\w$.]))(?P<r>[A-Za-z_$][\w$]*)\s*\.\s*(?P<m>[A-Za-z_$][\w$]*)\s*\(")
JAVA_CHAIN = re.compile(r"\)\s*\.\s*(?P<m>[A-Za-z_$][\w$]*)\s*\(")
JAVA_BARE = re.compile(r"(?<![\w$.:@])(?P<m>[a-z_$][\w$]*)\s*\(")
JAVA_NEW = re.compile(r"\bnew\s+(?P<t>[A-Z][\w$.]*)\s*(?:<[^<>()]*>)?\s*[(\[{]")
JAVA_REF = re.compile(r"(?<![\w$.])(?P<r>[A-Za-z_$][\w$]*)\s*::\s*(?P<m>[A-Za-z_$][\w$]*)")
JAVA_SEND = re.compile(r"(?P<r>[A-Za-z_$][\w$]*)\s*\.\s*(?P<m>(?:send|publish|push|produce)\w*)\s*\(\s*(?P<a>\"|[A-Za-z_$][\w$.]*)")
JAVA_PRODUCER = re.compile(r"kafka|producer|publisher", re.I)
JAVA_RECORD = re.compile(r"\bnew\s+ProducerRecord\s*(?:<[^<>()]*>)?\s*\(\s*(?P<a>\"|[A-Za-z_$][\w$.]*)")
JOOQ_ARG = r"\s*\(\s*(?P<a>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)(?=\s*[,).])"
JOOQ_WRITE = re.compile(r"\.\s*(?:insertInto|update|deleteFrom|delete|mergeInto)" + JOOQ_ARG)
JOOQ_READ = re.compile(r"\.\s*(?:from|selectFrom|join|leftJoin|rightJoin|innerJoin|fullJoin|fullOuterJoin|leftOuterJoin|"
                       r"rightOuterJoin|crossJoin|naturalJoin|leftSemiJoin|leftAntiJoin|straightJoin)" + JOOQ_ARG)
JAVA_ANN = re.compile(r"@(?P<n>[A-Za-z_$][\w$.]*)")
JAVA_MODS = re.compile(r"\b(?:public|protected|private|static|final|abstract|synchronized|native|default|strictfp|transient|"
                       r"volatile|sealed|non-sealed)\b")
JAVA_KW = {"if", "for", "while", "switch", "catch", "synchronized", "return", "new", "throw", "super", "this", "else", "try",
           "do", "assert", "case", "yield", "instanceof", "class", "interface", "enum", "record", "package", "import", "goto"}
JAVA_COMMON = {"String", "Integer", "Long", "Object", "List", "Map", "Set", "UUID", "BigDecimal", "LocalDate", "LocalDateTime",
               "Boolean", "Double", "Optional", "Collection", "Field", "Condition", "Record", "Result", "Table", "DSL", "Stream",
               "Instant", "OffsetDateTime", "Short", "Byte", "Float", "Character", "Iterable", "ArrayList", "HashMap", "HashSet"}
JOOQ_API = re.compile(r"^(?:DSLContext|DSL|SQL|Name|Query\w*|Select\w*|Insert\w*|Update\w*|Delete\w*|Merge\w*|Table\w*|"
                      r"Field\w*|Record\d*|Result\w*|Row\d*|Condition|CommonTableExpression|Configuration|Param|Sort\w*|"
                      r"Cursor|Batch\w*|With\w*|Derived\w*|Schema|Catalog|Sequence|Routine|Loader\w*)$")
MAPPINGS = {"GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT", "DeleteMapping": "DELETE", "PatchMapping": "PATCH",
            "RequestMapping": None}
STR_LIT = re.compile(r'"((?:\\.|[^"\\])*)"')


def strip_java(src: str) -> str:
    def blank(m: re.Match) -> str:
        s = m.group(0)
        if s[0] == "/":
            return re.sub(r"[^\n]", " ", s)
        q = 3 if s.startswith('"""') else 1
        return s[:q] + re.sub(r"[^\n]", " ", s[q:-q]) + s[-q:]

    return JAVA_NOISE.sub(blank, src)


def paren_end(text: str, i: int) -> int:
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j
    return -1


def decl_start(clean: str, i: int) -> int:
    depth, j = 0, i - 1
    while j >= 0:
        c = clean[j]
        if c == ")":
            depth += 1
        elif c == "(":
            depth -= 1
        elif depth == 0 and c in ";{}":
            return j + 1
        j -= 1
    return 0


def no_generics(s: str) -> str:
    prev = None
    while prev != s:
        prev, s = s, re.sub(r"<[^<>]*>", "", s)
    return s


def base_type(t: str) -> str:
    words = [w for w in no_generics(t).replace("...", " ").replace("[]", " ").split() if w != "final"]
    return words[-1] if words else ""


def squeeze(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def cut(text: str, a: int, b: int, spans: list[tuple[int, int]]) -> str:
    out, pos = [], a
    for s, e in sorted(spans):
        if s >= pos:
            out.append(text[pos:s])
        pos = max(pos, e)
    out.append(text[pos:b])
    return "".join(out)


def split_top(s: str) -> list[str]:
    out, depth, cur = [], 0, []
    for c in s:
        if c in "<([{":
            depth += 1
        elif c in ">)]}":
            depth -= 1
        if c == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    out.append("".join(cur))
    return [x.strip() for x in out if x.strip()]


def java_annotations(src: str, clean: str, a: int, b: int) -> tuple[dict[str, str], list[tuple[int, int]]]:
    anns: dict[str, str] = {}
    spans = []
    for m in JAVA_ANN.finditer(clean, a, b):
        k = m.end()
        while k < b and clean[k] in " \t\r\n":
            k += 1
        args, end = "", m.end()
        if k < b and clean[k] == "(":
            e = paren_end(clean, k)
            if e > 0:
                args, end = src[k + 1:e], e + 1
        anns.setdefault(m.group("n").rsplit(".", 1)[-1], args)
        spans.append((m.start(), end))
    return anns, spans


def blank_strings(s: str) -> str:
    return STR_LIT.sub(lambda m: '"' + " " * (len(m.group(0)) - 2) + '"', s)


def ann_attr(args: str, keys: tuple[str, ...]) -> str | None:
    plain = blank_strings(args)
    m = re.search(r"(?<![\w$])(?:%s)\s*=\s*" % "|".join(keys), plain)
    if not m:
        return None
    rest = plain[m.end():]
    if rest.startswith("{"):
        end = rest.find("}") + 1 or len(rest)
    else:
        nxt = re.search(r",\s*[A-Za-z_]\w*\s*=", rest)
        end = nxt.start() if nxt else len(rest)
    return args[m.end():m.end() + end]


def ann_values(args: str, keys: tuple[str, ...]) -> list[str] | None:
    seg = ann_attr(args, keys)
    if seg is None:
        plain = blank_strings(args).strip()
        if not plain or re.search(r"(?<![=!<>])=(?!=)", plain):
            return [""]
        seg = args
    vals = STR_LIT.findall(seg)
    if vals:
        return vals
    consts = re.findall(r"\b([A-Z][\w$]*\.[A-Z_][A-Z0-9_]*)\b", blank_strings(seg))
    return [f"const:{c}" for c in consts] or None


def split_aligned(text: str, plain: str, sep: str) -> list[tuple[str, str]]:
    out, depth, start = [], 0, 0
    for i, c in enumerate(plain):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == sep and depth == 0:
            out.append((text[start:i], plain[start:i]))
            start = i + 1
    out.append((text[start:], plain[start:]))
    return out


def path_exprs(seg: str) -> list[str]:
    seg = seg.strip()
    plain = blank_strings(seg)
    if plain.startswith("{") and plain.endswith("}"):
        seg, plain = seg[1:-1], plain[1:-1]
    out = []
    for item, item_plain in split_aligned(seg, plain, ","):
        parts = []
        for piece, _ in split_aligned(item, item_plain, "+"):
            piece = piece.strip()
            lit = STR_LIT.fullmatch(piece)
            if lit:
                parts.append(lit.group(1))
            elif re.fullmatch(r"[A-Za-z_$][\w$.]*", piece):
                parts.append(f"\u27e8{piece}\u27e9")
            elif piece:
                parts.append("{}")
        if parts:
            out.append("".join(parts))
    return out


def ann_paths(args: str) -> list[str]:
    seg = ann_attr(args, ("value", "path"))
    if seg is None:
        plain = blank_strings(args).strip()
        if not plain or re.search(r"(?<![=!<>])=(?!=)", plain):
            return [""]
        seg = args
    return path_exprs(seg) or [""]


def join_path(*parts: str) -> str:
    segs = [p.strip("/") for p in parts if p and p.strip("/")]
    return "/" + "/".join(segs)


def skip_blank(clean: str, i: int, end: int) -> int:
    while i < end and clean[i] in " \t\r\n":
        i += 1
    return i


def javadoc(src: str, a: int, b: int) -> str:
    docs = re.findall(r"/\*\*(.*?)\*/", src[a:b], re.S)
    if not docs:
        return ""
    for line in docs[-1].splitlines():
        line = line.strip().lstrip("*").strip()
        if line and not line.startswith("@"):
            return re.sub(r"\{@\w+\s+([^}]*)\}", r"\1", line)[:160]
    return ""


def snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def extract_java(rel: str, src: str) -> dict:
    clean = strip_java(src)
    lines = src.splitlines()
    is_test = is_test_file(rel)
    newlines = [m.start() for m in re.finditer("\n", clean)]

    def line_of(off: int) -> int:
        return bisect.bisect_left(newlines, off) + 1

    pm = re.search(r"^\s*package\s+([\w.]+)\s*;", clean, re.M)
    pkg = pm.group(1) if pm else ""
    defs = [{"id": rel, "kind": "module", "name": rel.rsplit("/", 1)[-1], "file": rel, "line": 1, "end": len(lines),
             "sig": pkg, "doc": "", "parent": None, "lang": "java"}]
    refs: list[dict] = []
    imports: dict[str, str] = {}
    wild: list[str] = []
    static_imp: dict[str, str] = {}
    table_cls: set[str] = set()
    table_consts: set[str] = set()
    tables_wild = tables_static = False
    for m in re.finditer(r"^\s*import\s+(static\s+)?([\w.]+?)(\.\*)?\s*;", clean, re.M):
        name, segs = m.group(2), m.group(2).split(".")
        if m.group(1):
            if m.group(3):
                tables_static = tables_static or segs[-1] == "Tables"
            else:
                static_imp[segs[-1]] = name
                if len(segs) > 1 and segs[-2] == "Tables":
                    table_consts.add(segs[-1])
            continue
        if m.group(3):
            wild.append(name)
            tables_wild = tables_wild or segs[-1] == "tables"
            continue
        imports[segs[-1]] = name
        refs.append({"src": rel, "kind": "imports", "target": name})
        if len(segs) > 1 and segs[-2] == "tables":
            table_cls.add(segs[-1])

    pairs: dict[int, int] = {}
    stack: list[int] = []
    bpos: list[int] = []
    bval: list[int] = []
    depth = 0
    for m in re.finditer(r"[{}]", clean):
        if m.group() == "{":
            stack.append(m.start())
            depth += 1
        else:
            if stack:
                pairs[stack.pop()] = m.start()
            depth -= 1
        bpos.append(m.start())
        bval.append(depth)

    def depth_at(off: int) -> int:
        i = bisect.bisect_left(bpos, off) - 1
        return bval[i] if i >= 0 else 0

    types: list[dict] = []
    for m in JAVA_TYPE.finditer(clean):
        op = clean.find("{", m.end())
        if op < 0 or op not in pairs or ";" in clean[m.end():op]:
            continue
        types.append({"kw": m.group("kw").lstrip("@"), "name": m.group("n"), "start": m.start(), "open": op, "close": pairs[op],
                      "fields": {}, "values": {}, "consts": {}})
    types.sort(key=lambda t: t["start"])

    def owner(pos: int) -> dict | None:
        best = None
        for t in types:
            if t["start"] > pos:
                break
            if t["open"] < pos < t["close"]:
                best = t
        return best

    consts: dict[str, str] = {}
    local_types: dict[str, str] = {}
    for t in types:
        outer = owner(t["start"])
        t["outer"] = outer
        t["id"] = f"{outer['id']}.{t['name']}" if outer else (f"{pkg}.{t['name']}" if pkg else t["name"])
        local_types.setdefault(t["name"], t["id"])
        hs = decl_start(clean, t["start"])
        anns, spans = java_annotations(src, clean, hs, t["start"])
        t["anns"] = anns
        header = no_generics(clean[t["start"]:t["open"]])
        if t["kw"] == "record":
            header = re.sub(r"\([^()]*\)", " ", header)
        for kw_re in (r"\bextends\s+(.+?)(?=\bimplements\b|\bpermits\b|$)", r"\bimplements\s+(.+?)(?=\bpermits\b|$)"):
            sm = re.search(kw_re, header, re.S)
            for sup in (sm.group(1).split(",") if sm else []):
                sup = sup.strip()
                if re.fullmatch(r"[\w$.]+", sup):
                    refs.append({"src": t["id"], "kind": "inherits", "target": sup, "cls": t["id"]})
        doc = " ".join([javadoc(src, hs, t["start"])] + [f"@{a}" for a in anns if a not in ("interface", "Override")]
                       + ([t["kw"]] if t["kw"] != "class" else [])).strip()
        defs.append({"id": t["id"], "kind": "class", "name": t["name"], "file": rel, "line": line_of(t["start"]),
                     "end": line_of(t["close"]), "sig": squeeze(cut(src, skip_blank(clean, hs, t["start"]), t["open"], spans))[:240],
                     "doc": doc[:200],
                     "parent": outer["id"] if outer else rel, "lang": "java"})
        t["feign"] = None
        if "FeignClient" in anns:
            a = anns["FeignClient"]
            name_seg = ann_attr(a, ("name", "value"))
            if name_seg is None and "=" not in blank_strings(a):
                name_seg = a
            path_seg = ann_attr(a, ("path",))
            t["feign"] = {"path": (path_exprs(path_seg) or [""])[0] if path_seg else "",
                          "client": {"url": " ".join(STR_LIT.findall(ann_attr(a, ("url",)) or "")),
                                     "name": " ".join(STR_LIT.findall(name_seg or ""))}}
        t["prefix"] = ann_paths(anns["RequestMapping"]) if "RequestMapping" in anns else [""]

    for m in JAVA_FIELD.finditer(clean):
        t = owner(m.start())
        tname = m.group("t")
        if not t or depth_at(m.start()) != depth_at(t["open"]) + 1 or tname.split(".")[0] in JAVA_KW or tname in ("var",):
            continue
        hs = decl_start(clean, m.start())
        anns, spans = java_annotations(src, clean, hs, m.start())
        head = cut(clean, hs, m.start(), spans)
        if "=" in head or "(" in head:
            continue
        name = m.group("n")
        t["fields"][name] = base_type(tname)
        if "Value" in anns:
            vals = STR_LIT.findall(anns["Value"])
            if vals:
                t["values"][name] = vals[0]
        if clean[m.end():m.end() + 3].lstrip().startswith("="):
            semi = clean.find(";", m.end())
            lit = re.fullmatch(r'\s*=\s*"((?:\\.|[^"\\])*)"\s*', src[m.end():semi]) if semi > 0 else None
            if lit:
                t["consts"][name] = lit.group(1)
                consts[f"{t['id']}.{name}"] = lit.group(1)

    members: list[dict] = []
    seen: dict[str, dict] = {}
    for m in JAVA_MEMBER.finditer(clean):
        name = m.group("n")
        if name in JAVA_KW:
            continue
        t = owner(m.start())
        if not t or depth_at(m.start()) != depth_at(t["open"]) + 1:
            continue
        po = m.end() - 1
        pc = paren_end(clean, po)
        if pc < 0:
            continue
        tail = JAVA_TAIL.match(clean, pc + 1)
        if not tail:
            continue
        hs = decl_start(clean, m.start())
        anns, aspans = java_annotations(src, clean, hs, m.start())
        head = cut(clean, hs, m.start(), aspans)
        if "=" in head or "->" in head or "." in head.strip()[-1:]:
            continue
        rest = squeeze(JAVA_MODS.sub(" ", no_generics(head)))
        if not rest and name != t["name"]:
            continue
        if rest and (not re.fullmatch(r"[\w$.\[\]]+", rest) or rest in JAVA_KW):
            continue
        _, pspans = java_annotations(src, clean, po + 1, pc)
        params = {}
        for p in split_top(cut(clean, po + 1, pc, pspans)):
            w = [x for x in p.replace("...", " ").split() if x != "final"]
            if len(w) >= 2:
                params[w[-1]] = base_type(" ".join(w[:-1]))
        mid = f"{t['id']}.{name}"
        if mid in seen:
            seen[mid]["overloads"] = seen[mid].get("overloads", 1) + 1
        else:
            d = {"id": mid, "kind": "method", "name": name, "file": rel, "line": line_of(m.start()), "end": line_of(pc),
                 "sig": squeeze(cut(src, skip_blank(clean, hs, m.start()), pc + 1, aspans))[:240],
                 "doc": " ".join([javadoc(src, hs, m.start())] + [f"@{a}" for a in anns if a != "Override"]).strip()[:200],
                 "parent": t["id"], "lang": "java"}
            defs.append(d)
            seen[mid] = d
        body = None
        if tail.group("e") == "{" and tail.start("e") in pairs:
            body = (tail.start("e"), pairs[tail.start("e")])
            seen[mid]["end"] = max(seen[mid]["end"], line_of(body[1]))
        members.append({"id": mid, "type": t, "anns": anns, "params": params, "body": body, "line": line_of(m.start())})
    for d in seen.values():
        if d.get("overloads"):
            d["sig"] = f"{d['sig']} (+{d.pop('overloads') - 1} overloads)"

    routes: list[dict] = []

    def chain(t: dict, key: str) -> dict:
        out: dict = {}
        while t:
            out = {**t[key], **out}
            t = t["outer"]
        return out

    def topic_arg(match: re.Match, t: dict, literal_ok: bool) -> str | None:
        a = match.group("a")
        if a == '"':
            lit = STR_LIT.match(src, match.start("a")) if literal_ok else None
            return lit.group(1) if lit else None
        if not literal_ok and "topic" not in a.lower() and "topic" not in chain(t, "values").get(a, "").lower():
            return None
        values, local_consts = chain(t, "values"), chain(t, "consts")
        if a in values:
            return values[a]
        if a in local_consts:
            return local_consts[a]
        return f"const:{a}" if "." in a else None

    for mb in members:
        t, anns, mid = mb["type"], mb["anns"], mb["id"]
        for ann, verb in MAPPINGS.items():
            if ann not in anns:
                continue
            paths = ann_paths(anns[ann])
            verbs = [verb] if verb else (re.findall(r"\b(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b", ann_attr(anns[ann], ("method",)) or "") or ["ANY"])
            if t["feign"]:
                for p in paths:
                    for v in verbs:
                        refs.append({"src": mid, "kind": "http", "method": v, "target": join_path(t["feign"]["path"], p),
                                     "client": t["feign"]["client"]})
            else:
                for pre in t["prefix"]:
                    for p in paths:
                        for v in verbs:
                            routes.append({"handler": mid, "method": v, "path": join_path(pre, p), "line": mb["line"]})
        listener = anns.get("KafkaListener")
        if listener is None and "KafkaHandler" in anns:
            listener = t["anns"].get("KafkaListener")
        if is_test:
            listener = None
        if listener is not None:
            for topic in ann_values(listener, ("topics", "value", "topicPattern")) or []:
                if topic:
                    refs.append({"src": mid, "kind": "consumes", "target": topic})
        if not mb["body"]:
            continue
        bo, bc = mb["body"]
        vt = {**chain(t, "fields"), **mb["params"]}
        for lm in JAVA_LOCAL.finditer(clean, bo, bc):
            vt[lm.group("n")] = base_type(lm.group("t"))
        for lm in JAVA_VAR.finditer(clean, bo, bc):
            vt[lm.group("n")] = lm.group("t")
        targets: set[str] = set()
        for c in JAVA_QCALL.finditer(clean, bo, bc):
            r, meth = c.group("r"), c.group("m")
            if r in ("this", "super"):
                targets.add(f"{r}.{meth}")
            elif r in vt:
                targets.add(f"{vt[r]}.{meth}")
            elif r[0].isupper():
                targets.add(f"{r}.{meth}")
            else:
                targets.add(f"?.{meth}")
        targets.update(f"?.{c.group('m')}" for c in JAVA_CHAIN.finditer(clean, bo, bc))
        targets.update(c.group("m") for c in JAVA_BARE.finditer(clean, bo, bc) if c.group("m") not in JAVA_KW)
        targets.update(f"new:{c.group('t')}" for c in JAVA_NEW.finditer(clean, bo, bc))
        for c in JAVA_REF.finditer(clean, bo, bc):
            r, meth = c.group("r"), c.group("m")
            if meth == "new":
                targets.add(f"new:{r}")
            elif r in ("this", "super"):
                targets.add(f"{r}.{meth}")
            elif r in vt:
                targets.add(f"{vt[r]}.{meth}")
            elif r[0].isupper():
                targets.add(f"{r}.{meth}")
        refs += [{"src": mid, "kind": "calls", "target": x, "cls": t["id"]} for x in sorted(targets)]
        for rx in (JAVA_SEND, JAVA_RECORD) if not is_test else ():
            for s in rx.finditer(clean, bo, bc):
                direct = rx is JAVA_RECORD or "KafkaTemplate" in vt.get(s.group("r"), "")
                if rx is JAVA_SEND and not (direct or JAVA_PRODUCER.search(s.group("r") + " " + vt.get(s.group("r"), ""))):
                    continue
                topic = topic_arg(s, t, direct)
                if topic:
                    refs.append({"src": mid, "kind": "publishes", "target": topic})
        for kind, rx in (("writes", JOOQ_WRITE), ("reads", JOOQ_READ)):
            for q in rx.finditer(clean, bo, bc):
                head, _, tail = q.group("a").partition(".")
                cls = const = None
                if not tail and head in vt:
                    cls = vt[head].rsplit(".", 1)[-1]
                elif tail and head == "Tables":
                    const = tail
                elif tail and head[:1].isupper() and re.fullmatch(r"[A-Z0-9_]+", tail):
                    cls = head
                elif not tail and re.fullmatch(r"[A-Z][A-Z0-9_]*", head) and (head in table_consts or tables_static):
                    const = head
                if const:
                    refs.append({"src": mid, "kind": kind, "target": const.lower(), "hint": "const"})
                elif cls and cls in table_cls:
                    refs.append({"src": mid, "kind": kind, "target": snake(cls), "hint": "explicit", "cls": cls})
                elif (cls and tables_wild and cls not in imports and cls not in JAVA_COMMON and cls not in local_types
                      and not JOOQ_API.match(cls)):
                    refs.append({"src": mid, "kind": kind, "target": snake(cls), "hint": "wildcard", "cls": cls})
    return {"lang": "java", "module": rel, "package": pkg, "defs": defs, "refs": refs, "imports": imports, "wild": wild,
            "static": static_imp, "routes": routes, "consts": consts, "local": local_types}


# ---------------------------------------------------------------------------------------------------------------
# build: per-file extraction cached by content hash, global resolution every time


def extract(repo: Path, rel: str) -> dict:
    src = (repo / rel).read_text(encoding="utf-8", errors="replace")
    try:
        if rel.endswith(".java"):
            return extract_java(rel, src)
        return extract_python(rel, src) if rel.endswith(".py") else extract_js(rel, src)
    except (SyntaxError, ValueError, RecursionError, IndexError, KeyError) as e:
        mod = rel if rel.endswith(".java") else py_module(rel) if rel.endswith(".py") else js_module(rel)
        return {"lang": "error", "module": mod, "package": "", "defs": [{"id": mod, "kind": "module", "name": mod, "file": rel,
                "line": 1, "end": 1, "sig": "", "doc": f"parse error: {type(e).__name__}", "parent": None, "lang": "?"}],
                "refs": [], "imports": {}}


def route_key(path: str) -> tuple[str, ...]:
    path = path.split("?", 1)[0].strip("/")
    segs = []
    for s in path.split("/") if path else []:
        segs.append("{}" if ("{" in s or s.startswith(":")) else s)
    return tuple(segs)


def route_match(routes: list[tuple[str, tuple, dict]], method: str, path: str) -> tuple[str | None, int, bool]:
    key = route_key(path)
    candidates = [key, ("api", *key)] + ([key[1:]] if key[:1] == ("api",) and len(key) > 1 else [])
    for candidate in candidates:
        best, best_score, tie = None, -1, False
        for m, k, rt in routes:
            if (m != method and "ANY" not in (m, method)) or len(k) != len(candidate):
                continue
            if all(a == b or a == "{}" or b == "{}" for a, b in zip(k, candidate)):
                score = sum(2 if a == b != "{}" else 1 if a == b else 0 for a, b in zip(k, candidate)) * 2 + (m != "ANY")
                if score > best_score:
                    best, best_score, tie = rt["handler"], score, False
                elif score == best_score and rt["handler"] != best:
                    tie = True
        if best:
            return best, best_score, tie
    return None, -1, False


def match_route(routes: list[tuple[str, tuple, dict]], method: str, path: str, unique: bool = False) -> str | None:
    best, _, tie = route_match(routes, method, path)
    return None if unique and tie else best


def is_global(nid: str | None) -> bool:
    return bool(nid) and (nid.startswith("topic:") or (nid.startswith("table:") and "." in nid))


def datasource_db(props: dict[str, str]) -> str:
    for key, value in props.items():
        if re.search(r"datasource.*url|jdbc.*url|r2dbc.*url|\bdb\.url|database\.url", key, re.I):
            m = re.search(r"(?:jdbc:\w+|postgres(?:ql)?|r2dbc:\w+)://[^/\s]+/([\w-]+)", expand(value, props))
            if m:
                return m.group(1)
    return ""


def java_type_of(name: str, f: dict, nodes: dict) -> str | None:
    if not name:
        return None
    head, _, tail = name.partition(".")
    cands = [f["local"].get(head), f["imports"].get(head), f"{f['package']}.{head}" if f["package"] else None]
    cands += [f"{w}.{head}" for w in f["wild"]] + [head]
    for c in cands:
        full = f"{c}.{tail}" if c and tail else c
        if full and full in nodes and nodes[full]["kind"] == "class":
            return full
    return None


def java_path(path: str, f: dict, nodes: dict, consts: dict[str, str], props: dict[str, str]) -> str:
    def const(m: re.Match) -> str:
        tp, _, nm = m.group(1).rpartition(".")
        if tp:
            tid = java_type_of(tp, f, nodes)
            val = consts.get(f"{tid}.{nm}") if tid else None
        else:
            val = next((v for k, v in f.get("consts", {}).items() if k.rsplit(".", 1)[-1] == nm), None)
            if val is None and nm in f.get("static", {}):
                val = consts.get(f["static"][nm])
        return val if val is not None else "{}"

    path = re.sub(r"\$\{[^}]*\}", "{}", expand(PATH_MARK.sub(const, path), props))
    return "/" + "/".join(x for x in path.split("/") if x)


def synthetic(nodes: dict, nid: str, kind: str, name: str, lang: str, sig: str = "") -> str:
    nodes.setdefault(nid, {"id": nid, "kind": kind, "name": name, "file": "", "line": 0, "end": 0, "sig": sig, "doc": "",
                           "parent": None, "lang": lang})
    return nid


def resolve(files: dict[str, dict], props: dict[str, str] | None = None) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    nodes = {d["id"]: d for f in files.values() for d in f["defs"]}
    by_name = defaultdict(list)
    for d in nodes.values():
        if d["kind"] != "module":
            by_name[d["name"]].append(d["id"])
    js_mods = {f["module"]: f for f in files.values() if f["lang"] == "ts"}
    py_imports = {f["module"]: f["imports"] for f in files.values() if f["lang"] == "python"}
    edges: set[tuple[str, str, str]] = set()
    ext: list[dict] = []

    def py_follow(full: str) -> str:
        for _ in range(4):
            if full in nodes:
                return full
            parts = full.split(".")
            for i in range(len(parts) - 1, 0, -1):
                target = py_imports.get(".".join(parts[:i]), {}).get(parts[i])
                if target and target != full:
                    full = ".".join([target, *parts[i + 1 :]])
                    break
            else:
                return full
        return full

    def js_target(src_mod: str, spec: str) -> str | None:
        if not spec.startswith("."):
            alias = spec.replace("@/", "src/", 1) if spec.startswith("@/") else None
            return next((m for m in js_mods if alias and m.endswith(alias)), None)
        base = os.path.normpath(os.path.join(os.path.dirname(src_mod), spec)).replace("\\", "/")
        base = re.sub(r"\.(tsx?|jsx?|mjs|cjs)$", "", base)
        return base if base in js_mods else (base[:-6] if base.endswith("/index") and base[:-6] in js_mods else None)

    props = props or {}
    jconsts = {k: v for f in files.values() if f["lang"] == "java" for k, v in f.get("consts", {}).items()}
    fixed = [{**rt, "path": java_path(rt["path"], f, nodes, jconsts, props) if f["lang"] == "java" else rt["path"]}
             for f in files.values() for rt in f.get("routes", [])]
    routes = [(rt["method"], route_key(rt["path"]), rt) for rt in fixed]
    for _, _, rt in routes:
        if rt["handler"] in nodes:
            n = nodes[rt["handler"]]
            label = f"{rt['method']} {rt['path']}"
            nodes[rt["handler"]] = {**n, "route": f"{n['route']}, {label}" if n.get("route") and label not in n["route"] else label}

    for f in files.values():
        mod, imports, lang = f["module"], f["imports"], f["lang"]
        if lang == "java":
            continue
        for r in f["refs"]:
            t, kind = r["target"], r["kind"]
            dst = None
            if kind == "http":
                base = r.get("base") or ""
                if base and lang == "ts" and base.split(".")[0] in imports:
                    spec, _, orig = imports[base.split(".")[0]].partition("#")
                    tm = js_target(mod, spec)
                    mod_consts = js_mods[tm].get("consts", {}) if tm else {}
                    if orig in mod_consts:
                        t, base = js_expand(mod_consts[orig] + t, mod_consts)
                if not t.startswith("/"):
                    continue
                dst = match_route(routes, r["method"], t)
                if not dst:
                    ext.append({"src": r["src"], "method": r["method"], "target": t, **({"base": base} if base else {})})
            elif kind == "imports":
                if lang == "ts":
                    dst = js_target(mod, t)
                else:
                    dst = t if t in nodes else (r.get("alt") if r.get("alt") in nodes else None)
            elif lang == "ts":
                head, _, tail = t.partition(".")
                if head in imports:
                    spec, _, orig = imports[head].partition("#")
                    tm = js_target(mod, spec)
                    if tm and orig == "default":
                        orig = (js_mods[tm].get("default") or f"{tm}#{head}").split("#", 1)[1]
                    if tm:
                        dst = f"{tm}#{orig}" + (f".{tail}" if tail and f"{tm}#{orig}.{tail}" in nodes else "")
                        dst = dst if dst in nodes else (tm if tm in nodes else None)
                elif f"{mod}#{head}" in nodes:
                    dst = f"{mod}#{head}"
            else:
                head, _, tail = t.partition(".")
                if head == "self" and r.get("cls") and tail and f"{r['cls']}.{tail.split('.')[0]}" in nodes:
                    dst = f"{r['cls']}.{tail.split('.')[0]}"
                elif head in imports:
                    full = py_follow(imports[head] + (f".{tail}" if tail else ""))
                    while full and full not in nodes and "." in full:
                        full = full.rsplit(".", 1)[0]
                    dst = full if full in nodes and full != imports[head].split(".")[0] or full in nodes else None
                elif f"{r.get('scope', mod)}.{t}" in nodes:
                    dst = f"{r.get('scope', mod)}.{t}"
                elif not tail and len(by_name.get(head, [])) == 1 and kind == "inherits":
                    dst = by_name[head][0]
                elif tail and kind == "calls":
                    meth = [i for i in by_name.get(tail.rsplit(".", 1)[-1], []) if nodes[i]["kind"] == "method"]
                    dst = meth[0] if len(meth) == 1 else None
            if dst and dst != r["src"] and dst in nodes:
                edges.add((r["src"], dst, kind))
    java = [f for f in files.values() if f["lang"] == "java"]
    if java:
        resolve_java(java, nodes, edges, by_name, props, ext, jconsts)
    for d in list(nodes.values()):
        if d["parent"] and d["parent"] in nodes:
            edges.add((d["parent"], d["id"], "contains"))
    return (list(nodes.values()), [{"src": a, "dst": b, "kind": k} for a, b, k in sorted(edges)], ext,
            [{"handler": rt["handler"], "method": rt["method"], "path": rt["path"]} for rt in fixed])


def resolve_java(jfiles: list[dict], nodes: dict, edges: set, by_name: dict, props: dict[str, str], ext: list[dict],
                 consts: dict[str, str]) -> None:
    children: dict[str, dict[str, str]] = defaultdict(dict)
    for d in nodes.values():
        if d["parent"] and d["lang"] == "java":
            children[d["parent"]].setdefault(d["name"], d["id"])
    db = datasource_db(props)
    methods_by_name: dict[str, list[str]] = defaultdict(list)
    for d in nodes.values():
        if d["lang"] == "java" and d["kind"] == "method":
            methods_by_name[d["name"]].append(d["id"])

    def type_of(name: str, f: dict) -> str | None:
        return java_type_of(name, f, nodes)

    supers: dict[str, list[str]] = defaultdict(list)
    for f in jfiles:
        for r in f["refs"]:
            if r["kind"] == "inherits":
                dst = type_of(r["target"], f)
                if dst and dst != r["src"]:
                    supers[r["src"]].append(dst)
                    edges.add((r["src"], dst, "inherits"))

    def ancestors(tid: str) -> list[str]:
        out, q, seen = [], deque(supers.get(tid, [])), {tid}
        while q:
            t = q.popleft()
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
            q.extend(supers.get(t, []))
        return out

    def find_method(tid: str | None, name: str) -> str | None:
        if not tid:
            return None
        for t in [tid, *ancestors(tid)]:
            c = children.get(t, {}).get(name)
            if c and nodes[c]["kind"] == "method":
                return c
        return None

    for sub in list(supers):
        for anc in ancestors(sub):
            for name, cid in children.get(anc, {}).items():
                own = children.get(sub, {}).get(name)
                if own and nodes[cid]["kind"] == "method" and nodes[own]["kind"] == "method":
                    edges.add((cid, own, "impl"))

    def topic_names(raw: str, f: dict) -> list[str]:
        if raw.startswith("const:"):
            tp, _, nm = raw[6:].rpartition(".")
            tid = type_of(tp, f)
            raw = consts.get(f"{tid}.{nm}") if tid else None
            if raw is None:
                return []
        spel = re.fullmatch(r"#\{\s*'(.*)'\s*\.split\(\s*'(.)'\s*\)\s*\}", raw.strip())
        if spel:
            return [x.strip() for x in expand(spel.group(1), props).split(spel.group(2)) if x.strip()]
        name = expand(raw, props).strip()
        return [name] if name else []

    for f in jfiles:
        for r in f["refs"]:
            kind, t = r["kind"], r["target"]
            dst = None
            if kind == "imports":
                dst = t if t in nodes else None
            elif kind == "calls":
                cls = r.get("cls")
                if t.startswith("new:"):
                    dst = type_of(t[4:], f)
                elif t.startswith("?."):
                    ms = methods_by_name.get(t[2:], [])
                    dst = ms[0] if len(ms) == 1 else None
                elif t.startswith("this."):
                    dst = find_method(cls, t[5:])
                elif t.startswith("super."):
                    dst = next((m for m in (find_method(s, t[6:]) for s in supers.get(cls, [])) if m), None)
                elif "." in t:
                    tp, _, meth = t.rpartition(".")
                    dst = find_method(type_of(tp, f), meth)
                else:
                    c = cls
                    while c and not dst:
                        dst = find_method(c, t)
                        up = nodes[c]["parent"] if c in nodes else None
                        c = up if up in nodes and nodes[up]["kind"] == "class" else None
                    if not dst and t in f["static"]:
                        full = f["static"][t]
                        dst = full if full in nodes else None
            elif kind == "http":
                client = dict(r.get("client") or {})
                url = client.get("url", "")
                ph = PLACEHOLDER.search(url)
                client["prop"] = ph.group(1) if ph else ""
                client["url"] = expand(url, props)
                ext.append({"src": r["src"], "method": r["method"], "target": java_path(t, f, nodes, consts, props), "client": client})
                continue
            elif kind in ("publishes", "consumes"):
                for name in topic_names(t, f):
                    tid = synthetic(nodes, f"topic:{name}", "topic", name, "kafka", t)
                    edges.add((r["src"], tid, "publishes") if kind == "publishes" else (tid, r["src"], "consumes"))
                continue
            elif kind in ("reads", "writes"):
                if r.get("hint") == "wildcard" and any(nodes[i]["kind"] == "class" for i in by_name.get(r.get("cls", ""), [])):
                    continue
                edges.add((r["src"], synthetic(nodes, f"table:{db}.{t}" if db else f"table:{t}", "table", t, "sql", db), kind))
                continue
            if dst and dst != r["src"] and dst in nodes:
                edges.add((r["src"], dst, kind))


def protect(repo: Path) -> None:
    exclude = repo / ".git" / "info" / "exclude"
    if exclude.parent.is_dir():
        text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if f"{OUT_DIR}/" not in text.split():
            exclude.write_text(text.rstrip("\n") + ("\n" if text else "") + f"{OUT_DIR}/\n", encoding="utf-8")


def map_path(repo: Path) -> Path:
    return repo / OUT_DIR / "codemap.json"


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def build(repo: Path, full: bool = False) -> dict:
    repo = repo.resolve()
    out = map_path(repo)
    cache_file = repo / OUT_DIR / "cache.json"
    cache = {}
    if not full and cache_file.is_file():
        try:
            old = json.loads(cache_file.read_text(encoding="utf-8"))
            cache = old.get("files", {}) if old.get("version") == VERSION else {}
        except (OSError, ValueError):
            cache = {}
    files, new_cache, parsed = {}, {}, 0
    for rel in discover(repo):
        h = hashlib.sha1((repo / rel).read_bytes()).hexdigest()
        if rel in cache and cache[rel]["sha"] == h:
            files[rel] = cache[rel]["data"]
        else:
            files[rel] = extract(repo, rel)
            parsed += 1
        new_cache[rel] = {"sha": h, "data": files[rel]}
    props = load_props(repo) if any(f["lang"] == "java" for f in files.values()) else {}
    nodes, edges, ext, routes = resolve(files, props)
    out.parent.mkdir(exist_ok=True)
    write_json(out, {"version": VERSION, "root": str(repo), "built": datetime.now().isoformat(timespec="seconds"),
                     "files": len(files), "parsed": parsed, "nodes": nodes, "edges": edges, "routes": routes, "ext": ext})
    write_json(cache_file, {"version": VERSION, "files": new_cache})
    protect(repo)
    return {"repo": str(repo), "files": len(files), "parsed": parsed, "nodes": len(nodes), "edges": len(edges)}


# ---------------------------------------------------------------------------------------------------------------
# queries


TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|e2e|spec)/|(^|/)test_[^/]*\.py$|_test\.py$|\.(test|spec)\.[jt]sx?$|(Tests?|IT)\.java$")


def is_test_file(path: str) -> bool:
    return bool(TEST_FILE.search(path))


class CodeMap:
    def __init__(self, repo: Path):
        self.repo = repo.resolve()
        self.map_file = map_path(self.repo)
        self.mtime = 0.0
        self.load()

    def load(self) -> None:
        if not self.map_file.is_file():
            raise FileNotFoundError(f"no Code Map for {self.repo}; build it with: python codemap.py build {self.repo}")
        st = self.map_file.stat().st_mtime
        if st == self.mtime:
            return
        d = json.loads(self.map_file.read_text(encoding="utf-8"))
        self.meta = {k: d[k] for k in ("root", "built", "files")}
        self.set_graph({n["id"]: n for n in d["nodes"]}, [(e["src"], e["dst"], e["kind"]) for e in d["edges"]])
        self.mtime = st

    def set_graph(self, nodes: dict, edges: list[tuple[str, str, str]]) -> None:
        self.nodes = nodes
        self.out, self.inc = defaultdict(list), defaultdict(list)
        for a, b, k in edges:
            self.out[a].append((b, k))
            self.inc[b].append((a, k))

    def brief(self, nid: str) -> str:
        n = self.nodes[nid]
        return f"{nid} L{n['line']}" if n["line"] else nid

    def degree(self, nid: str) -> int:
        return sum(1 for _, k in self.out[nid] if k != "contains") + sum(1 for _, k in self.inc[nid] if k != "contains")

    def find(self, name: str) -> list[str]:
        if name in self.nodes:
            return [name]
        low = name.lower()
        exact = [i for i, n in self.nodes.items() if n["name"].lower() == low or i.lower().endswith(("." + low, "#" + low))]
        exact.sort(key=lambda i: (self.nodes[i]["kind"] == "module", -self.degree(i)))
        return exact or self.search_ids(name, 5)

    def search_ids(self, query: str, limit: int, tests: bool = False) -> list[str]:
        words = [w for w in re.split(r"\W+", query.lower()) if len(w) > 1]
        if not words:
            return []
        scores = Counter()
        for i, n in self.nodes.items():
            hay_name = (n["name"] + " " + i).lower()
            hay_doc = (n["doc"] + " " + n["file"]).lower()
            s = sum(3 for w in words if w in n["name"].lower()) + sum(1 for w in words if w in hay_name) + sum(1 for w in words if w in hay_doc)
            if s:
                if is_test_file(n["file"]) and not tests:
                    continue
                scores[i] = s + min(self.degree(i), 20) / 20
        return [i for i, _ in scores.most_common(limit)]

    def symbol(self, name: str, limit: int = 25) -> dict:
        ids = self.find(name)
        if not ids:
            return {"error": f"nothing named {name!r}"}
        nid = ids[0]
        n = self.nodes[nid]

        def rel(pairs: list, kinds: set) -> list[str]:
            return sorted({self.brief(x) for x, k in pairs if k in kinds})[:limit]

        def prod_callers(target: str) -> set[str]:
            return {self.brief(x) for x, k in self.inc[target] if k == "calls" and not is_test_file(self.nodes[x]["file"])}

        via = set().union(*(prod_callers(x) for x, k in self.inc[nid] if k == "impl")) if n["kind"] == "method" else set()
        return {"symbol": nid, "kind": n["kind"], "location": f"{n['file']}:{n['line']}-{n['end']}" if n["file"] else "",
                "signature": n["sig"], "route": n.get("route", ""), "http_callers": rel(self.inc[nid], {"http"}),
                "http_calls": rel(self.out[nid], {"http"}), "doc": n["doc"],
                "callers": sorted(prod_callers(nid))[:limit], "callers_via_interface": sorted(via)[:limit],
                "tested_by": [r["test"] for r in self.tests_for(nid, depth=1)][:10],
                "callees": rel(self.out[nid], {"calls"}),
                "implements": rel(self.inc[nid], {"impl"}), "implemented_by": rel(self.out[nid], {"impl"}),
                "publishes": rel(self.out[nid], {"publishes"}), "consumes": rel(self.inc[nid], {"consumes"}),
                "producers": rel(self.inc[nid], {"publishes"}), "consumers": rel(self.out[nid], {"consumes"}),
                "reads_tables": rel(self.out[nid], {"reads"}), "writes_tables": rel(self.out[nid], {"writes"}),
                "readers": rel(self.inc[nid], {"reads"}), "writers": rel(self.inc[nid], {"writes"}),
                "imported_by": rel(self.inc[nid], {"imports"}), "imports": rel(self.out[nid], {"imports"}),
                "inherits": rel(self.out[nid], {"inherits"}), "subclasses": rel(self.inc[nid], {"inherits"}),
                "members": rel(self.out[nid], {"contains"}), "other_matches": ids[1:6]}

    def tests_for(self, nid: str, depth: int = 3) -> list[dict]:
        """Tests that reach `nid` through calls (or HTTP), nearest first: walk callers backwards up to `depth` hops,
        through helpers and fixtures, and keep the nodes that live in test files."""
        found, seen, q = {}, {nid}, deque([(nid, 0, [])])
        while q:
            cur, d, chain = q.popleft()
            if d >= depth:
                continue
            for x, k in self.inc[cur]:
                if k not in ("calls", "http", "impl") or x in seen:
                    continue
                seen.add(x)
                via = [*chain, cur] if cur != nid else chain
                if is_test_file(self.nodes[x]["file"]):
                    found.setdefault(x, {"test": self.brief(x), "hops": d + 1, "via": [self.brief(v) for v in via]})
                q.append((x, d + 1, via))
        return sorted(found.values(), key=lambda r: (r["hops"], r["test"]))

    def tests(self, name: str, depth: int = 3, limit: int = 40) -> dict:
        ids = self.find(name)
        if not ids:
            return {"error": f"nothing named {name!r}"}
        rows = self.tests_for(ids[0], depth)
        files = sorted({self.nodes[r["test"].rsplit(" L", 1)[0]]["file"] for r in rows})
        return {"symbol": ids[0], "direct": sum(1 for r in rows if r["hops"] == 1), "indirect": sum(1 for r in rows if r["hops"] > 1),
                "test_files": files, "tests": rows[:limit],
                "note": "" if rows else "no test reaches this symbol through static calls (it may be tested through an API client, a fixture or not at all)"}

    def neighbors(self, name: str, depth: int = 1, limit: int = 60) -> dict:
        ids = self.find(name)
        if not ids:
            return {"error": f"nothing named {name!r}"}
        start, seen, q, rows = ids[0], {ids[0]}, deque([(ids[0], 0)]), []
        while q and len(rows) < limit:
            cur, d = q.popleft()
            if d >= depth:
                continue
            for nxt, k in self.out[cur] + [(x, f"{k} (in)") for x, k in self.inc[cur]]:
                if nxt not in seen:
                    seen.add(nxt)
                    rows.append({"from": cur, "to": nxt, "edge": k, "where": f"{self.nodes[nxt]['file']}:{self.nodes[nxt]['line']}"})
                    q.append((nxt, d + 1))
        return {"symbol": start, "depth": depth, "neighbors": rows[:limit]}

    def path(self, a: str, b: str) -> dict:
        sa, sb = self.find(a), self.find(b)
        if not sa or not sb:
            return {"error": "symbol not found: " + (a if not sa else b)}
        for directed in (True, False):
            prev, q = {sa[0]: None}, deque([sa[0]])
            while q:
                cur = q.popleft()
                if cur == sb[0]:
                    chain = []
                    while cur:
                        chain.append(cur)
                        cur = prev[cur]
                    chain.reverse()
                    return {"from": sa[0], "to": sb[0], "directed": directed, "hops": len(chain) - 1,
                            "path": [self.brief(x) for x in chain]}
                if directed:
                    nxt = [x for x, k in self.out[cur] if k != "contains"]
                else:  # a shared import (config, utils) is not a meaningful connection
                    nxt = [x for x, k in self.out[cur] + self.inc[cur] if k in ("calls", "inherits")]
                for x in nxt:
                    if x not in prev:
                        prev[x] = cur
                        q.append(x)
        return {"from": sa[0], "to": sb[0], "path": None,
                "note": "no static connection; the flow may go through a queue, an HTTP call or a registry (search for the producer and consumer)"}

    def hubs(self, limit: int = 20, kind: str | None = None) -> dict:
        ids = [i for i, n in self.nodes.items() if n["kind"] != "module" and (not kind or n["kind"] == kind)]
        top = sorted(ids, key=lambda i: -self.degree(i))[:limit]
        return {"hubs": [{"symbol": i, "degree": self.degree(i), "where": f"{self.nodes[i]['file']}:{self.nodes[i]['line']}"} for i in top]}

    def file(self, rel: str) -> dict:
        rel = rel.replace("\\", "/")
        hits = [n for n in self.nodes.values() if n["file"] == rel or n["file"].endswith("/" + rel)]
        if not hits:
            return {"error": f"no mapped file {rel!r}"}
        return {"file": hits[0]["file"], "symbols": [{"symbol": n["id"], "kind": n["kind"], "line": n["line"], "signature": n["sig"]}
                                                     for n in sorted(hits, key=lambda n: n["line"])]}

    def routes(self, query: str = "", limit: int = 60) -> dict:
        """HTTP routes with their handler and the frontend code that calls them."""
        rows = []
        for nid, n in self.nodes.items():
            if n.get("route") and query.lower() in (n["route"] + " " + nid).lower():
                callers = sorted({self.brief(x) for x, k in self.inc[nid] if k == "http"})
                rows.append({"route": n["route"], "handler": self.brief(nid), "called_from": callers})
        rows.sort(key=lambda r: r["route"].split(" ", 1)[1])
        unmatched = sum(1 for v in self.out.values() for _, k in v if k == "http")
        return {"routes": len(rows), "shown": rows[:limit], "frontend_calls_linked": unmatched}

    def stats(self) -> dict:
        kinds = Counter(n["kind"] for n in self.nodes.values())
        langs = Counter(n["lang"] for n in self.nodes.values() if n["kind"] == "module")
        edges = Counter(k for v in self.out.values() for _, k in v)
        areas = Counter("/".join(n["file"].split("/")[:2]) for n in self.nodes.values() if n["kind"] != "module")
        return {**self.meta, "symbols_by_kind": dict(kinds), "modules_by_language": dict(langs), "edges_by_kind": dict(edges),
                "largest_areas": dict(areas.most_common(12)), "errors": [n["file"] for n in self.nodes.values() if n["doc"].startswith("parse error")][:10]}

    def search(self, query: str, limit: int = 15, tests: bool = False) -> dict:
        ids = self.search_ids(query, limit, tests) or self.search_ids(query, limit, True)
        return {"query": query, "results": [{"symbol": i, "kind": self.nodes[i]["kind"], "where": f"{self.nodes[i]['file']}:{self.nodes[i]['line']}",
                                             "signature": self.nodes[i]["sig"], "doc": self.nodes[i]["doc"],
                                             "callers": len([1 for _, k in self.inc[i] if k == "calls"]),
                                             "callees": len([1 for _, k in self.out[i] if k == "calls"])} for i in ids]}


    def data(self, kind: str = "", query: str = "", limit: int = 40) -> dict:
        rows = []
        q = query.lower()
        for nid, n in self.nodes.items():
            if n["kind"] not in ("topic", "table") or (kind and n["kind"] != kind) or q not in nid.lower():
                continue
            if n["kind"] == "topic":
                a = sorted({self.brief(x) for x, k in self.inc[nid] if k == "publishes"})
                b = sorted({self.brief(x) for x, k in self.out[nid] if k == "consumes"})
                row = {"topic": n["name"], "property": n["sig"], "producers": len(a), "consumers": len(b)}
                if q:
                    row |= {"producer_list": a[:20], "consumer_list": b[:20]}
            else:
                a = sorted({self.brief(x) for x, k in self.inc[nid] if k == "writes"})
                b = sorted({self.brief(x) for x, k in self.inc[nid] if k == "reads"})
                row = {"table": n["name"], "writers": len(a), "readers": len(b)}
                if q:
                    row |= {"writer_list": a[:25], "reader_list": b[:15]}
            rows.append(row)
        rows.sort(key=lambda r: r.get("topic") or r.get("table"))
        return {"total": len(rows), "shown": rows[:limit],
                "note": "" if q else "pass a query (part of a topic or table name) to list the producers, consumers, writers and readers"}


GENERIC_REPO_WORDS = {"service", "services", "svc", "api", "backend", "frontend", "web", "app", "server", "client",
                      "integration", "core", "ts", "js", "v1", "v2", "v3"}


def repo_hinted(repo: str, hint: str, generic: set[str] = GENERIC_REPO_WORDS) -> bool:
    words = [w for w in re.split(r"[^a-z0-9]+", repo.lower()) if w and w not in generic]
    return bool(words) and all(w in hint for w in words)


class Workspace(CodeMap):
    def __init__(self, repos: list[Path], targets: dict[str, list[str]] | None = None, generic_words: list[str] | None = None):
        self.repos = [r.resolve() for r in repos]
        self.targets = targets or {}
        self.generic = GENERIC_REPO_WORDS | {w.lower() for w in generic_words or []}
        self.stamp: tuple = ()
        self.repo = self.repos[0]
        self.load()

    def load(self) -> None:
        present = [(r, map_path(r)) for r in self.repos if map_path(r).is_file()]
        if not present:
            raise FileNotFoundError("no Code Map in any mapped repo; build them with: python codemap.py build <repo>")
        stamp = tuple((str(f), f.stat().st_mtime) for _, f in present)
        if stamp == self.stamp:
            return
        nodes: dict = {}
        edges: set = set()
        by_repo: dict[str, list] = defaultdict(list)
        ext: list[dict] = []
        built, nfiles = [], 0
        for repo, f in present:
            d = json.loads(f.read_text(encoding="utf-8"))
            name = repo.name

            def pre(i: str | None) -> str | None:
                return i if i is None or is_global(i) else f"{name}:{i}"

            for n in d["nodes"]:
                nid = pre(n["id"])
                if nid in nodes and is_global(nid):
                    continue
                nodes[nid] = {**n, "id": nid, "file": f"{name}/{n['file']}" if n["file"] else "", "parent": pre(n["parent"])}
            edges.update((pre(e["src"]), pre(e["dst"]), e["kind"]) for e in d["edges"])
            for rt in d.get("routes", []):
                by_repo[name].append((rt["method"], route_key(rt["path"]), {**rt, "handler": pre(rt["handler"])}))
            ext += [{**x, "src": pre(x["src"]), "repo": name} for x in d.get("ext", [])]
            built.append(d.get("built", ""))
            nfiles += d.get("files", 0)
        for x in ext:
            hint = re.sub(r"[^a-z0-9]", "", " ".join([x.get("base", ""), *map(str, (x.get("client") or {}).values())]).lower())
            hinted = [r for r in by_repo if r != x["repo"] and hint and repo_hinted(r, hint, self.generic)]
            if hinted:
                dst = match_route([rt for r in hinted for rt in by_repo[r]], x["method"], x["target"])
            else:
                targets = [rt for r in self.targets.get(x["repo"], []) for rt in by_repo.get(r, [])]
                others = [rt for r, rts in by_repo.items() if r != x["repo"] for rt in rts]
                d1, s1, _ = route_match(targets, x["method"], x["target"])
                d2, s2, t2 = route_match(others, x["method"], x["target"])
                dst = d1 if d1 and (s1 >= s2 or t2) else (None if t2 else d2)
            if dst and dst in nodes:
                edges.add((x["src"], dst, "http"))
        self.meta = {"root": f"{len(present)} repos: " + ", ".join(r.name for r, _ in present), "built": max(built), "files": nfiles}
        self.set_graph(nodes, sorted(edges))
        self.stamp = stamp


# ---------------------------------------------------------------------------------------------------------------
# MCP server


def project_config() -> tuple[list[Path], dict]:
    for start in (os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()):
        if not start:
            continue
        d = Path(start).resolve()
        for p in (d, *d.parents):
            f = p / ".claude" / "kit.json"
            if f.is_file():
                cfg = (json.loads(f.read_text(encoding="utf-8")).get("codemap") or {})
                return [(p / x).resolve() for x in cfg.get("dirs") or ["."]], cfg
    return [Path.cwd().resolve()], {}


def project_repos() -> list[Path]:
    return project_config()[0]


REPO_ARG = {"repo": {"type": "string", "description": "one repository folder name; by default all mapped repos are served as "
                                                      "one map, linked across services (ids are prefixed with the folder name)"}}
TOOLS = {
    "codemap_search": ("Find functions, classes, methods and modules by words (names, annotations, docstrings, file paths). "
                       "Start here.",
                       {"query": {"type": "string"}, "limit": {"type": "integer"},
                        "tests": {"type": "boolean", "description": "include test code (default false)"}}, ["query"]),
    "codemap_symbol": ("One symbol: location, signature, route, callers (also through interfaces), callees, implementations, "
                       "Kafka topics it publishes or consumes, DB tables it reads or writes, imports, inheritance, members. "
                       "Also works on topic:<name> and table:<name>.",
                       {"name": {"type": "string", "description": "short or qualified name"}}, ["name"]),
    "codemap_neighbors": ("Everything connected to a symbol up to a depth (calls, imports, inheritance, both directions).",
                          {"name": {"type": "string"}, "depth": {"type": "integer"}}, ["name"]),
    "codemap_path": ("How symbol A reaches symbol B through calls, interface implementations, HTTP calls between services "
                     "and Kafka topics (shortest chain).",
                     {"source": {"type": "string"}, "target": {"type": "string"}}, ["source", "target"]),
    "codemap_hubs": ("The most connected symbols: the places most of the code flows through.",
                     {"limit": {"type": "integer"}, "kind": {"type": "string", "description": "function, class, method"}}, []),
    "codemap_routes": ("HTTP API routes (method, path, handler: Spring, FastAPI, Flask) and the frontend functions or Feign "
                       "clients that call each one. Filter by a path or name fragment.",
                       {"query": {"type": "string"}, "limit": {"type": "integer"}}, []),
    "codemap_data": ("Kafka topics with their producers and consumers, and DB tables (jOOQ) with the methods that write and "
                     "read them. Filter by part of a topic or table name to get the lists.",
                     {"kind": {"type": "string", "description": "topic or table (default both)"}, "query": {"type": "string"},
                      "limit": {"type": "integer"}}, []),
    "codemap_tests": ("Tests that cover a symbol: direct test callers and tests that reach it through helpers, with the chain "
                      "and the test files to run.", {"name": {"type": "string"}, "depth": {"type": "integer", "description": "hops, 1 to 5 (default 3)"}}, ["name"]),
    "codemap_file": ("All symbols defined in one file with line numbers and signatures.", {"path": {"type": "string"}}, ["path"]),
    "codemap_stats": ("Size of the map: repos, files, symbols by kind, languages, edges, largest areas, build time.", {}, []),
}


def prune(obj):
    """Drop empty values so answers cost fewer tokens."""
    if isinstance(obj, dict):
        return {k: prune(v) for k, v in obj.items() if v not in (None, "", [], {})}
    if isinstance(obj, list):
        return [prune(v) for v in obj]
    return obj


def compact(data: dict) -> str:
    return json.dumps(prune(data), ensure_ascii=False, separators=(",", ":"))


def serve() -> None:
    maps: dict[str, CodeMap] = {}

    def get(repo: str | None) -> CodeMap:
        repos, cfg = project_config()
        if not repo and len(repos) > 1:
            if "*" not in maps:
                maps["*"] = Workspace(repos, cfg.get("http_targets"), cfg.get("generic_words"))
            maps["*"].load()
            return maps["*"]
        target = next((r for r in repos if repo and r.name == repo), None)
        if target is None:
            if repo:
                raise ValueError(f"unknown repo {repo!r}; mapped: {', '.join(r.name for r in repos)}")
            target = repos[0]
        key = str(target)
        if key not in maps:
            maps[key] = CodeMap(target)
        maps[key].load()
        return maps[key]

    def call(name: str, a: dict) -> dict:
        m = get(a.get("repo"))
        if name == "codemap_search":
            return m.search(a["query"], int(a.get("limit", 15)), bool(a.get("tests", False)))
        if name == "codemap_symbol":
            return m.symbol(a["name"])
        if name == "codemap_neighbors":
            return m.neighbors(a["name"], min(int(a.get("depth", 1)), 3))
        if name == "codemap_path":
            return m.path(a["source"], a["target"])
        if name == "codemap_hubs":
            return m.hubs(int(a.get("limit", 20)), a.get("kind"))
        if name == "codemap_routes":
            return m.routes(a.get("query", ""), int(a.get("limit", 60)))
        if name == "codemap_data":
            return m.data(a.get("kind", ""), a.get("query", ""), int(a.get("limit", 40)))
        if name == "codemap_tests":
            return m.tests(a["name"], max(1, min(int(a.get("depth", 3)), 5)))
        if name == "codemap_file":
            return m.file(a["path"])
        return m.stats()

    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            mid, method = msg.get("id"), msg.get("method")
            if mid is None:
                continue
            if method == "initialize":
                result = {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                          "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "naki-codemap", "version": str(VERSION)}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [{"name": n, "description": d, "annotations": {"readOnlyHint": True},
                                     "inputSchema": {"type": "object", "properties": {**props, **REPO_ARG}, "required": req}}
                                    for n, (d, props, req) in TOOLS.items()]}
            elif method == "tools/call":
                p = msg.get("params", {})
                if p.get("name") not in TOOLS:
                    resp = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {p.get('name')}"}}
                    sys.stdout.buffer.write((json.dumps(resp) + "\n").encode())
                    sys.stdout.buffer.flush()
                    continue
                try:
                    data = call(p["name"], p.get("arguments") or {})
                    result = {"content": [{"type": "text", "text": compact(data)}], "isError": False}
                except Exception as e:  # report and keep serving
                    result = {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
            else:
                resp = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
                sys.stdout.buffer.write((json.dumps(resp) + "\n").encode())
                sys.stdout.buffer.flush()
                continue
            resp = {"jsonrpc": "2.0", "id": mid, "result": result}
        sys.stdout.buffer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("build", "info", "query", "serve"):
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "serve":
        serve()
        return 0
    repo = Path(sys.argv[2] if len(sys.argv) > 2 else ".").resolve()
    if cmd == "build":
        print(json.dumps(build(repo, full="--full" in sys.argv)))
    elif cmd == "info":
        try:
            print(json.dumps(CodeMap(repo).stats(), ensure_ascii=False, indent=1))
        except FileNotFoundError as e:
            print(json.dumps({"error": str(e)}))
            return 1
    else:
        print(json.dumps(CodeMap(repo).search(" ".join(sys.argv[3:])), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
