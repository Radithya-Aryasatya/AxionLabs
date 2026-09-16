"""Compile-check the app + solver packages and report to _pc_out.txt."""
import io
import os
import py_compile
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = [
    "app.py",
    "solver_common/schemas.py",
    "solver_common/interface.py",
    "solver_common/__init__.py",
    "solver_classic/adapter.py",
    "solver_classic/__init__.py",
    "solver_sardine/baseline.py",
    "solver_sardine/improver.py",
    "solver_sardine/memory.py",
    "solver_sardine/__init__.py",
]

out = []
for rel in FILES:
    path = os.path.join(HERE, rel.replace("/", os.sep))
    if not os.path.exists(path):
        out.append("MISSING  %s" % rel)
        continue
    try:
        src = io.open(path, encoding="utf-8").read()
        compile(src, path, "exec")
    except SyntaxError as e:
        out.append("SYNTAX   %s  line %s: %s" % (rel, e.lineno, e.msg))
    except Exception as e:  # noqa: BLE001
        out.append("ERROR    %s  %r" % (rel, e))
    else:
        out.append("OK       %s" % rel)
        py_compile.compile(path, cfile=os.path.join(HERE, "_pc_tmp.pyc"),
                           doraise=False)

io.open(os.path.join(HERE, "_pc_out.txt"), "w", encoding="utf-8").write(
    "\n".join(out) + "\n")
sys.stdout.write("\n".join(out) + "\n")
