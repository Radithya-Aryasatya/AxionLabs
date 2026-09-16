"""Temporary: safely remove the two corrupted solver files and report status."""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
TARGETS = ["solver_sardine/memory.py", "solver_sardine/improver.py"]
lines = []
for rel in TARGETS:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    try:
        if os.path.exists(p):
            os.remove(p)
            lines.append(f"removed {rel} exists_now={os.path.exists(p)}")
        else:
            lines.append(f"absent {rel}")
    except OSError as e:
        lines.append(f"FAILED {rel}: {e}")
with open(os.path.join(ROOT, "_cleanup_out.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("\n".join(lines))