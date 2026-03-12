"""Static analysis of user scripts to detect language and third-party imports.

Pure string processing — no subprocess calls, no Julia/Python required locally.
Used to generate appropriate environment setup instructions in the AI prompt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScriptEnvironment:
    """Summary of a script's language and dependency requirements."""

    language: str                    # "julia", "python", "shell", "unknown"
    has_manifest: bool               # Project.toml / requirements.txt found
    third_party_imports: list[str]   # Non-stdlib packages, sorted alphabetically
    driver_extension: str            # ".jl", ".py", ".sh", or ""


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_script(
    script_content: str | None,
    driver_script: str | None,
    manifest_content: str | None,
) -> ScriptEnvironment:
    """Detect language, manifest presence, and third-party imports.

    Args:
        script_content:   Raw text of the driver script, or None if not provided.
        driver_script:    Relative or absolute path of the driver script
                          (used for extension-based language detection).
        manifest_content: Contents of Project.toml / requirements.txt / pyproject.toml,
                          or None if not found.
    """
    ext = Path(driver_script).suffix.lower() if driver_script else ""
    language = _detect_language(ext, script_content or "")
    has_manifest = bool(manifest_content and manifest_content.strip())

    third_party: list[str] = []
    if script_content:
        if language == "julia":
            third_party = _julia_third_party(script_content)
        elif language == "python":
            third_party = _python_third_party(script_content)
        # shell / unknown: no package analysis needed

    return ScriptEnvironment(
        language=language,
        has_manifest=has_manifest,
        third_party_imports=third_party,
        driver_extension=ext,
    )


# ── Language detection ────────────────────────────────────────────────────────

def _detect_language(ext: str, content: str) -> str:
    if ext == ".jl":
        return "julia"
    if ext in (".py", ".pyw"):
        return "python"
    if ext in (".sh", ".bash"):
        return "shell"

    # Fall back to shebang on the first non-empty line.
    for line in content.splitlines():
        line = line.strip()
        if line:
            if "julia" in line:
                return "julia"
            if "python" in line:
                return "python"
            if "bash" in line or "/sh" in line:
                return "shell"
            break  # Only check the first non-empty line

    return "unknown"


# ── Julia ─────────────────────────────────────────────────────────────────────

# Standard library packages shipped with Julia — must not be Pkg.add'd.
_JULIA_STDLIB: frozenset[str] = frozenset({
    "Base", "Core", "Dates", "DelimitedFiles", "Distributed",
    "FileWatching", "Future", "InteractiveUtils", "Libdl", "LibGit2",
    "LinearAlgebra", "Logging", "Markdown", "Mmap", "Pkg", "Printf",
    "Profile", "REPL", "Random", "SHA", "Serialization", "SharedArrays",
    "Sockets", "SparseArrays", "Statistics", "SuiteSparse", "Test",
    "Unicode", "UUIDs",
})

# Matches:  using Foo         using Foo, Bar, Baz
#           import Foo        import Foo: f, g      import Foo.Sub
_JULIA_IMPORT_RE = re.compile(
    r"^\s*(?:using|import)\s+(.+?)(?:\s*#.*)?$",
    re.MULTILINE,
)


def _julia_third_party(content: str) -> list[str]:
    """Return sorted list of non-stdlib packages found in Julia source."""
    packages: set[str] = set()
    for match in _JULIA_IMPORT_RE.finditer(content):
        raw = match.group(1)
        # "import A: f, g" — everything after ":" are function names, not packages.
        if ":" in raw:
            raw = raw.split(":")[0]
        for item in raw.split(","):
            # Strip ".SubModule" qualifiers — keep only the top-level package name.
            name = re.split(r"[.\s]", item.strip())[0]
            if re.fullmatch(r"[A-Za-z]\w*", name) and name not in _JULIA_STDLIB:
                packages.add(name)
    return sorted(packages)


# ── Python ────────────────────────────────────────────────────────────────────

# Standard library module names (Python 3.9-compatible hardcoded set).
_PYTHON_STDLIB: frozenset[str] = frozenset({
    "__future__", "_thread", "abc", "aifc", "argparse", "array", "ast",
    "asynchat", "asyncio", "asyncore", "atexit", "audioop", "base64",
    "bdb", "binascii", "binhex", "bisect", "builtins", "bz2", "calendar",
    "cgi", "cgitb", "chunk", "cmath", "cmd", "code", "codecs", "codeop",
    "collections", "colorsys", "compileall", "concurrent", "configparser",
    "contextlib", "contextvars", "copy", "copyreg", "csv", "ctypes",
    "curses", "dataclasses", "datetime", "dbm", "decimal", "difflib",
    "dis", "distutils", "doctest", "email", "encodings", "enum", "errno",
    "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch", "fractions",
    "ftplib", "functools", "gc", "getopt", "getpass", "gettext", "glob",
    "grp", "gzip", "hashlib", "heapq", "hmac", "html", "http", "imaplib",
    "imp", "importlib", "inspect", "io", "ipaddress", "itertools", "json",
    "keyword", "linecache", "locale", "logging", "lzma", "mailbox",
    "marshal", "math", "mimetypes", "mmap", "multiprocessing", "netrc",
    "numbers", "operator", "optparse", "os", "pathlib", "pdb", "pickle",
    "pickletools", "pkgutil", "platform", "plistlib", "poplib", "pprint",
    "profile", "pstats", "pwd", "queue", "random", "re", "readline",
    "reprlib", "resource", "runpy", "sched", "secrets", "select",
    "selectors", "shelve", "shlex", "shutil", "signal", "site", "smtplib",
    "socket", "socketserver", "sqlite3", "ssl", "stat", "statistics",
    "string", "struct", "subprocess", "sys", "sysconfig", "tarfile",
    "tempfile", "test", "textwrap", "threading", "time", "timeit",
    "tkinter", "token", "tokenize", "tomllib", "trace", "traceback",
    "tracemalloc", "types", "typing", "unicodedata", "unittest", "urllib",
    "uuid", "venv", "warnings", "wave", "weakref", "webbrowser",
    "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo",
    # Typing backport — effectively always present, not worth installing explicitly.
    "typing_extensions",
})

_PYTHON_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+([A-Za-z_]\w*(?:\.\w+)*)|from\s+([A-Za-z_]\w*(?:\.\w+)*)\s+import)",
    re.MULTILINE,
)


def _python_third_party(content: str) -> list[str]:
    """Return sorted list of non-stdlib packages found in Python source."""
    packages: set[str] = set()
    for match in _PYTHON_IMPORT_RE.finditer(content):
        name = match.group(1) or match.group(2)
        if not name:
            continue
        top = name.split(".")[0]   # "sklearn.model_selection" → "sklearn"
        if top and top not in _PYTHON_STDLIB:
            packages.add(top)
    return sorted(packages)
