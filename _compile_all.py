"""Temporary: syntax-check every Python file touched by the solver work."""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

FILES = [
    "app.py",
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
ok = True
for rel in FILES:
    path = os.path.join(HERE, rel.replace("/", os.sep))
    if not os.path.exists(path):
        out.append("MISSING  %s" % rel)
        ok = False
        continue
    src = io.open(path, encoding="utf-8-sig").read()
    try:
        compile(src, path, "exec")
        out.append("OK       %-32s (%d lines)" % (rel, len(src.splitlines())))
    except SyntaxError as e:
        ok = False
        out.append("SYNTAX   %s  line %s: %s" % (rel, e.lineno, e.msg))

out.append("")
out.append("RESULT: " + ("ALL FILES COMPILE" if ok else "THERE WERE FAILURES"))
text = "\n".join(out)
io.open(os.path.join(HERE, "_compile_all.txt"), "w", encoding="utf-8").write(text + "\n")
sys.stdout.write(text.encode("ascii", "replace").decode("ascii") + "\n")
sys.exit(0 if ok else 1)
