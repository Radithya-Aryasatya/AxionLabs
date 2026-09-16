"""Temporary: compile-check every project python file and report failures."""
import io
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TARGETS = [
    "app.py",
    "executive_dashboard.py",
    "orientation_editor.py",
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

out = []
for rel in TARGETS:
    path = os.path.join(HERE, rel.replace("/", os.sep))
    if not os.path.exists(path):
        out.append("MISSING  %s" % rel)
        continue
    src = io.open(path, encoding="utf-8-sig").read()
    try:
        compile(src, path, "exec")
        out.append("OK       %s  (%d lines)" % (rel, len(src.splitlines())))
    except SyntaxError as e:
        out.append("SYNTAX   %s  line %s: %s" % (rel, e.lineno, e.msg))
        if e.text:
            out.append("         %r" % e.text)
    except Exception as e:
        out.append("ERROR    %s  %r" % (rel, e))

text = "\n".join(out)
io.open(os.path.join(HERE, "_syntax_out.txt"), "w", encoding="utf-8").write(text + "\n")
sys.stdout.write(text.encode("ascii", "replace").decode("ascii") + "\n")
