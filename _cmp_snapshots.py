"""Temp: compare live solver modules against the _tmp_inspect snapshots."""
import difflib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "_tmp_inspect")

PAIRS = [
    ("solver_sardine/memory.py", "memory_snapshot.txt"),
    ("solver_sardine/improver.py", "improver_snapshot.txt"),
    ("solver_sardine/baseline.py", "baseline_snapshot.txt"),
    ("solver_sardine/__init__.py", "sardine_init_snapshot.txt"),
]

out = []
for live_rel, snap_name in PAIRS:
    live_path = os.path.join(HERE, live_rel.replace("/", os.sep))
    snap_path = os.path.join(SNAP, snap_name)
    if not (os.path.exists(live_path) and os.path.exists(snap_path)):
        out.append("SKIP %s / %s" % (live_rel, snap_name))
        continue
    a = io.open(live_path, encoding="utf-8-sig").read().splitlines()
    b = io.open(snap_path, encoding="utf-8-sig").read().splitlines()
    d = list(difflib.unified_diff(b, a, "snapshot:" + snap_name,
                                  "live:" + live_rel, lineterm="", n=1))
    if d:
        out.append("### DIFF %s (%d diff lines)" % (live_rel, len(d)))
        out.extend(d[:120])
    else:
        out.append("IDENTICAL %s" % live_rel)
    out.append("")

text = "\n".join(out)
io.open(os.path.join(HERE, "_cmp_out.txt"), "w", encoding="utf-8").write(text + "\n")
sys.stdout.write(text.encode("ascii", "replace").decode("ascii") + "\n")