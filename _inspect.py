"""Temporary diagnostic helper - reports syntax status of the solver package."""
import os
import py_compile
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
FILES = [
    "solver_common/__init__.py",
    "solver_common/schemas.py",
    "solver_common/interface.py",
    "solver_classic/__init__.py",
    "solver_classic/adapter.py",
    "solver_sardine/__init__.py",
    "solver_sardine/baseline.py",
    "solver_sardine/memory.py",
    "solver_sardine/improver.py",
]

out = []
for rel in FILES:
    path = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.exists(path):
        out.append(f"{rel}: MISSING")
        continue
    with open(path, encoding="utf-8") as f:
        src = f.read()
    lines = src.splitlines()
    status = "OK"
    detail = ""
    try:
        compile(src, path, "exec")
    except SyntaxError as e:
        status = "SYNTAX_ERROR"
        detail = f" line {e.lineno}: {e.msg}"
    except Exception as e:  # noqa: BLE001
        status = "ERROR"
        detail = f" {type(e).__name__}: {e}"
    out.append(f"{rel}: lines={len(lines)} bytes={len(src)} {status}{detail}")

with open(os.path.join(ROOT, "_inspect_out.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(out) + "\n")
print("\n".join(out))