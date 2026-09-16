"""Temporary: dump real on-disk content of the solver package to one file."""
import os
import hashlib

ROOT = os.path.dirname(os.path.abspath(__file__))
FILES = [
    "solver_sardine/memory.py",
    "solver_sardine/improver.py",
    "solver_sardine/baseline.py",
    "solver_common/schemas.py",
    "solver_common/interface.py",
    "solver_classic/adapter.py",
    "solver_sardine/__init__.py",
]

parts = []
for rel in FILES:
    path = os.path.join(ROOT, rel.replace("/", os.sep))
    st = os.stat(path)
    parts.append("=" * 78)
    parts.append(f"FILE {rel}  size={st.st_size} mtime={st.st_mtime:.0f}")
    parts.append("=" * 78)
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            parts.append(f"{i:4d}| {line.rstrip()}")

with open(os.path.join(ROOT, "_dump_out.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(parts) + "\n")
print("done", len(parts))