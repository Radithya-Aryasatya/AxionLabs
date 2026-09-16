"""Diagnostic: dump a numbered, indent-annotated line range of a file."""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
target = os.path.join(HERE, sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, "app.py")
lo = int(sys.argv[2]) if len(sys.argv) > 2 else 1
hi = int(sys.argv[3]) if len(sys.argv) > 3 else lo + 59

text = io.open(target, "rb").read().decode("utf-8-sig")
lines = text.splitlines()
out = ["FILE %s  lines=%d" % (os.path.basename(target), len(lines))]
for i in range(lo - 1, min(len(lines), hi)):
    ln = lines[i]
    out.append("%4d|%3d| %s" % (i + 1, len(ln) - len(ln.lstrip()), ln.rstrip()))
for ln in out:
    try:
        print(ln)
    except UnicodeEncodeError:
        print(ln.encode("ascii", "replace").decode("ascii"))