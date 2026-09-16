"""One-shot patch: add an `ensure_dirs` alias to solver_sardine/memory.py.

app.py imports `ensure_dirs`, but memory.py currently only defines
`ensure_store`.  This script inserts a thin alias (keeping both names
working) and records the result in a log file.
"""
import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "solver_sardine", "memory.py")
LOG = os.path.join(HERE, "_patch_log.txt")

log = []

with io.open(TARGET, encoding="utf-8") as fh:
    src = fh.read()

if "def ensure_dirs" in src:
    log.append("ensure_dirs already present - no change")
else:
    anchor = '_README_TEXT = """# AI Progress Store'
    idx = src.find(anchor)
    if idx == -1:
        log.append("FAIL: anchor not found")
    else:
        alias = (
            "def ensure_dirs() -> bool:\n"
            '    """Backwards-compatible alias for :func:`ensure_store`.\n'
            "\n"
            "    ``app.py`` imports ``ensure_dirs``; the store bootstrap was\n"
            '    later renamed to ``ensure_store``. Keeping both names working\n'
            '    means either import style is safe.\n'
            '    """\n'
            "    return ensure_store()\n"
            "\n"
            "\n"
        )
        src = src[:idx] + alias + src[idx:]
        # Also export it.
        src = re.sub(r'(\n\s*"ensure_store",)', r'\1\n    "ensure_dirs",', src, count=1)
        with io.open(TARGET, "w", encoding="utf-8", newline="") as fh:
            fh.write(src)
        log.append("inserted ensure_dirs alias before _README_TEXT")
        log.append("__all__ updated: %s" % ('"ensure_dirs",' in src))

# Verify it compiles and the names exist.
try:
    import ast
    ast.parse(src if 'src' in dir() else io.open(TARGET, encoding="utf-8").read())
    log.append("AST parse OK")
except SyntaxError as exc:
    log.append("AST parse FAIL: %s" % exc)

with io.open(LOG, "w", encoding="utf-8") as fh:
    fh.write("\n".join(log))
print("\n".join(log))
