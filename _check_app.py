"""Developer check: compile app.py + solver packages and report branch shape.

Run:  python _check_app.py
"""
import ast
import io
import os
import py_compile
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_check_app_out.txt")

FILES = [
    "app.py",
    "solver_common/__init__.py",
    "solver_common/schemas.py",
    "solver_common/interface.py",
    "solver_classic/__init__.py",
    "solver_classic/adapter.py",
    "solver_sardine/__init__.py",
    "solver_sardine/baseline.py",
    "solver_sardine/improver.py",
    "solver_sardine/memory.py",
]

lines = []


def log(msg):
    lines.append(msg)


log("=== 1. COMPILE CHECK ===")
ok = True
for rel in FILES:
    path = os.path.join(HERE, rel)
    if not os.path.exists(path):
        ok = False
        log(f"MISSING  {rel}")
        continue
    try:
        py_compile.compile(path, cfile=path + "c", doraise=True)
        log(f"OK       {rel}")
    except py_compile.PyCompileError as e:
        ok = False
        log(f"FAIL     {rel}: {e.msg}")
    except Exception as e:  # noqa: BLE001
        ok = False
        log(f"ERROR    {rel}: {e!r}")

log("")
log("=== 2. CLASSIC / SARDINE BRANCH SHAPE (app.py) ===")
try:
    src = io.open(os.path.join(HERE, "app.py"), encoding="utf-8-sig").read()
    tree = ast.parse(src, filename="app.py")
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name):
            if node.test.id == "use_sardine" and node.lineno > 1000:
                if "engine" not in found:
                    found["engine"] = node.lineno
                elif "run" not in found:
                    found["run"] = node.lineno
    log(f"if use_sardine nodes (line>1000): {found or 'none'}")
    for key in ("Packer()", "addBin(", "_classic_order", "if not use_sardine:"):
        log(f"contains {key!r}: {key in src}")
except Exception:  # noqa: BLE001
    ok = False
    log(traceback.format_exc())

log("")
log("=== 3. IMPORT CHECK (solver packages) ===")
sys.path.insert(0, HERE)
for mod in ("solver_common", "solver_common.schemas", "solver_common.interface",
            "solver_classic", "solver_classic.adapter",
            "solver_sardine", "solver_sardine.baseline",
            "solver_sardine.improver", "solver_sardine.memory"):
    try:
        __import__(mod)
        log(f"OK       import {mod}")
    except Exception as e:  # noqa: BLE001
        ok = False
        log(f"FAIL     import {mod}: {type(e).__name__}: {e}")

log("")
log("=== RESULT ===")
log("ALL CHECKS PASSED" if ok else "THERE WERE FAILURES")

with io.open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines))
sys.exit(0 if ok else 1)
