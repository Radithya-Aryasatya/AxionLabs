"""Diagnostic: report app.py parse status and dump a line range (dev-only)."""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")

raw = io.open(APP, "rb").read()
has_bom = raw.startswith(b"\xef\xbb\xbf")
text = raw.decode("utf-8-sig")
lines = text.splitlines()

out = []
out.append("bytes=%d lines=%d bom=%s newline=%r"
           % (len(raw), len(lines), has_bom,
              "\r\n" if "\r\n" in text else "\n"))

try:
    compile(text, APP, "exec")
    out.append("SYNTAX OK")
except SyntaxError as e:
    out.append("SYNTAX FAIL line %s: %s" % (e.lineno, e.msg))
    for i in range(max(0, (e.lineno or 1) - 8), min(len(lines), (e.lineno or 1) + 4)):
        out.append("%4d|%3d| %s" % (i + 1, len(lines[i]) - len(lines[i].lstrip()),
                                    lines[i].strip()))
    payload = "\n".join(out)
    io.open(os.path.join(HERE, "_inspect_app.txt"), "w", encoding="utf-8").write(
        payload)
    sys.stdout.write(payload.encode("ascii", "replace").decode("ascii") + "\n")
    sys.exit(0)

lo, hi = 1505, 1565
if len(sys.argv) > 2:
    lo, hi = int(sys.argv[1]), int(sys.argv[2])
out.append("")
out.append("--- lines %d..%d ---" % (lo, hi))
for i in range(lo - 1, min(len(lines), hi)):
    out.append("%4d|%3d| %s" % (i + 1, len(lines[i]) - len(lines[i].lstrip()),
                                lines[i].strip()))

payload = "\n".join(out)
io.open(os.path.join(HERE, "_inspect_app.txt"), "w", encoding="utf-8").write(payload)
sys.stdout.write(payload.encode("ascii", "replace").decode("ascii") + "\n")