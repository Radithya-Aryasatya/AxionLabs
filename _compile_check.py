"""Temporary: syntax-check the solver packages + app.py."""
import py_compile
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
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
for rel in FILES:
    path = os.path.join(HERE, rel)
    try:
        py_compile.compile(path, doraise=True,
                           cfile=os.path.join(HERE, "_pyc_tmp.pyc"))
        lines.append("OK   " + rel)
    except py_compile.PyCompileError as e:
        msg = str(e).replace("\n", " | ")
        lines.append("FAIL " + rel + " -> " + msg)
    except Exception as e:  # noqa: BLE001
        lines.append("ERR  " + rel + " " + repr(e))
        lines.append(traceback.format_exc())

with open(os.path.join(HERE, "_compile_log.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("\n".join(lines))
sys.exit(0 if all(l.startswith("OK") for l in lines) else 1)
