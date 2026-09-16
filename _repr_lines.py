"""Diagnostic: show raw repr of specific app.py lines (dev-only)."""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, "app.py")
lo = int(sys.argv[2]) if len(sys.argv) > 2 else 1515
hi = int(sys.argv[3]) if len(sys.argv) > 3 else 1522

text = io.open(APP, "rb").read().decode("utf-8-sig")
lines = text.splitlines(keepends=True)
for i in range(lo - 1, min(len(lines), hi)):
    out = "%4d %s" % (i + 1, repr(lines[i]))
    try:
        print(out)
    except UnicodeEncodeError:
        print(out.encode("ascii", "replace").decode("ascii"))
print("--- newline census ---")
print("CRLF lines:", sum(1 for l in lines if l.endswith("\r\n")))
print("LF-only  :", sum(1 for l in lines if l.endswith("\n") and not l.endswith("\r\n")))
print("no-EOL   :", sum(1 for l in lines if not l.endswith("\n")))
print("tab lines:", sum(1 for l in lines if "\t" in l))