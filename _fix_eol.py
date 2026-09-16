"""Normalise app.py line endings to CRLF and report the caret positions."""
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "app.py")

with io.open(PATH, "r", encoding="utf-8", newline="") as fh:
    raw = fh.read()

norm = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
changed = norm != raw
if changed:
    with io.open(PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write(norm)

lines = norm.split("\r\n")
lf_only = [i + 1 for i, ln in enumerate(raw.split("\n")) if False]
no_eol = 1 if not norm.endswith("\r\n") else 0

out = []
out.append("CHANGED=%s" % changed)
out.append("total lines = %d" % len(lines))
out.append("no-EOL tail = %d" % no_eol)
out.append("CRLF lines  = %d" % (len(lines) - no_eol))
out.append("tab-indented lines = %d" % len([l for l in lines if l.startswith("\t")]))

if changed:
    import py_compile
    try:
        py_compile.compile(PATH, doraise=True)
        out.append("COMPILE OK")
    except Exception as exc:  # noqa: BLE001
        out.append("COMPILE FAIL: %r" % (exc,))

with io.open(os.path.join(HERE, "_eol_out.txt"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(out) + "\n")
print("\n".join(out))
