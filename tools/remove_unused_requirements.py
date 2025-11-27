#!/usr/bin/env python3
"""Detect unused packages from requirements.txt and suggest uninstall commands.

Usage:
  python tools/remove_unused_requirements.py [--apply]

By default the script prints a report and the `pip uninstall` commands to run.
If `--apply` is passed, it will ask for confirmation and then run `pip uninstall -y` for each package.

This is best-effort: package names in requirements may not match module names exactly.
Always review the suggested removals before applying.
"""
import ast
import os
import re
import codecs
import subprocess
import sys
from typing import Dict, List, Set


ROOT = os.path.dirname(os.path.dirname(__file__))
REQ_PATH = os.path.join(ROOT, "requirements.txt")


def parse_requirements(path: str) -> List[str]:
    if not os.path.exists(path):
        print(f"requirements file not found: {path}")
        return []
    pkgs = []
    # read raw bytes and detect BOM/encoding to handle UTF-16 or other encodings
    raw = open(path, "rb").read()
    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        enc = "utf-16"
    elif raw.startswith(codecs.BOM_UTF8):
        enc = "utf-8-sig"
    else:
        # try utf-8, fallback to latin-1
        try:
            raw.decode("utf-8")
            enc = "utf-8"
        except Exception:
            enc = "latin-1"

    text = raw.decode(enc, errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # remove environment markers and version specs
        # keep the package string before any [extras], ==, >=, <=, ~=, @
        # match the first package-like token anywhere on the line (robust to stray chars/BOM)
        m = re.search(r"([A-Za-z0-9_.\-\[\]]+)", line)
        if not m:
            continue
        pkg = m.group(1)
        # strip extras like package[extra]
        pkg = re.split(r"\[", pkg)[0]
        pkgs.append(pkg)
    return pkgs


def find_python_files(root: str) -> List[str]:
    py_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # skip virtualenvs and __pycache__
        if ".venv" in dirpath or "venv" in dirpath or "__pycache__" in dirpath:
            continue
        for fn in filenames:
            if fn.endswith(".py"):
                py_files.append(os.path.join(dirpath, fn))
    return py_files


def collect_imported_modules(py_files: List[str]) -> Set[str]:
    imports: Set[str] = set()
    for p in py_files:
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                node = ast.parse(fh.read(), filename=p)
        except Exception:
            continue
        for n in ast.walk(node):
            if isinstance(n, ast.Import):
                for alias in n.names:
                    name = alias.name.split(".")[0]
                    imports.add(name)
            elif isinstance(n, ast.ImportFrom):
                if n.module:
                    name = n.module.split(".")[0]
                    imports.add(name)
    return imports


COMMON_ALIASES: Dict[str, str] = {
    # mapping common PyPI package names -> top-level import module
    "python-dateutil": "dateutil",
    "firebase-admin": "firebase_admin",
    "google-api-core": "google",
    "python-dotenv": "dotenv",
    "Flask-SocketIO": "flask_socketio",
    "flask-socketio": "flask_socketio",
    "requests": "requests",
    "unidecode": "unidecode",
}


def match_package_to_import(pkg: str, imports: Set[str]) -> bool:
    lower_pkg = pkg.lower()
    # direct matches
    if lower_pkg in imports or pkg in imports:
        return True
    # replace hyphen with underscore
    if lower_pkg.replace("-", "_") in imports:
        return True
    # try common alias
    mapped = COMMON_ALIASES.get(pkg) or COMMON_ALIASES.get(lower_pkg)
    if mapped and mapped in imports:
        return True
    # try prefix matching: some packages provide modules without dash
    for imp in imports:
        if imp.lower().startswith(lower_pkg.split("-")[0]):
            return True
    return False


def main():
    apply = "--apply" in sys.argv

    pkgs = parse_requirements(REQ_PATH)
    if not pkgs:
        print("No packages found in requirements.txt")
        return

    py_files = find_python_files(ROOT)
    imports = collect_imported_modules(py_files)

    used = []
    unused = []
    for pkg in pkgs:
        if match_package_to_import(pkg, imports):
            used.append(pkg)
        else:
            unused.append(pkg)

    print("Detected imports (sample):", list(sorted(imports))[:30])
    print()
    print(f"Total packages in requirements: {len(pkgs)}")
    print(f"Used (by import heuristic): {len(used)}")
    print(f"Unused (candidates): {len(unused)}")
    print()
    if unused:
        print("Candidate packages to uninstall:")
        for p in unused:
            print(f"  - {p}")

        print()
        print("Suggested pip uninstall commands:")
        for p in unused:
            print(f"pip uninstall -y {p}")

        print()
        print("If you want to update requirements.txt to remove these entries, run:")
        print(f"python -c \"open('{REQ_PATH}','w').write('\n'.join({used}) )\"")

        if apply:
            confirm = input("About to uninstall listed packages. Continue? [y/N]: ")
            if confirm.strip().lower() == "y":
                for p in unused:
                    print(f"Uninstalling {p}...")
                    subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", p])
                # update requirements.txt
                with open(REQ_PATH, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(used) + "\n")
                print("requirements.txt updated.")
            else:
                print("Aborted.")
    else:
        print("No unused packages detected by heuristic.")


if __name__ == "__main__":
    main()
