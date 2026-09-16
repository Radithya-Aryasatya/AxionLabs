"""Dump ground-truth copies of the solver sources + mtimes (diagnostic)."""
import os
import shutil
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "_dump")
os.makedirs(OUT, exist_ok=True)

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

lines = []
for rel in FILES:
    path = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.exists(path):
        lines.append(f"{rel}\tMISSING")
        continue
    st = os.stat(path)
    flat = rel.replace("/", "__")
    shutil.copyfile(path, os.path.join(OUT, flat + ".txt"))
    lines.append(
        f"{rel}\tsize={st.st_size}\tmtime={time.strftime('%H:%M:%S', time.localtime(st.st_mtime))}"
    )

with open(os.path.join(ROOT, "_inspect_out.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("\n".join(lines))
