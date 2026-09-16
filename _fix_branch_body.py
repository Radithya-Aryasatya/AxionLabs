"""One-off repair: indent app.py's Sardine-Can branch body (dev-only).

``_fix_app_sardine.py`` rebuilt the ``if use_sardine:`` header at the correct
12-space depth, but the branch *body* ended up level with the header instead
of nested inside it, so ``app.py`` still failed to parse with
``expected an indented block after 'if' statement``.

This script finds that header and pushes everything up to the classic
``else:`` (recognised by the ``packer = Packer()`` that follows it) one level
deeper.  CRLF line endings and the UTF-8 BOM are preserved.

Run:  python _fix_branch_body.py
"""
import io
import os
import py_compile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")

SPINNER = '        with st.spinner("Running 3D bin packing optimization..."):'
SARDINE_IF = "            if use_sardine:"
CLASSIC_ELSE = "            else:"
CLASSIC_FIRST = "                packer = Packer()"


def _indent(line):
    return len(line) - len(line.lstrip())


def main():
    with io.open(APP, "rb") as fh:
        raw = fh.read()
    bom = b"\xef\xbb\xbf"
    has_bom = raw.startswith(bom)
    text = raw.decode("utf-8-sig" if has_bom else "utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)

    # ─ Locate the spinner block, then its engine branch ──────────────
    spinner = None
    for i, ln in enumerate(lines):
        if ln.rstrip("\r\n") == SPINNER:
            spinner = i
            break
    assert spinner is not None, "spinner anchor not found"

    head = spinner + 1
    assert lines[head].rstrip("\r\n") == SARDINE_IF, \
        "expected sardine header after spinner, got %r" % lines[head]

    # The branch ends where the classic engine branch starts.
    tail = None
    for j in range(head + 1, len(lines)):
        if (lines[j].rstrip("\r\n") == CLASSIC_ELSE and
                j + 1 < len(lines) and
                lines[j + 1].rstrip("\r\n") == CLASSIC_FIRST):
            tail = j
            break
    assert tail is not None, "classic 'else:' not found after the branch"

    # Idempotence guard: a correct body already starts at 16 spaces.
    first = head + 1
    while lines[first].strip() == "":
        first += 1
    if _indent(lines[first]) == 16:
        print("app.py already repaired - nothing to do (%d lines)"
              % len(text.splitlines()))
        py_compile.compile(APP, doraise=True)
        return

    assert _indent(lines[first]) == 12, \
        "unexpected body indent %d on line %d" % (_indent(lines[first]),
                                                  first + 1)

    # ── Push the branch body one level deeper ─────────────────────────
    body = []
    for ln in lines[head + 1:tail]:
        stripped = ln.rstrip("\r\n")
        if stripped.strip() == "":
            body.append(nl)
            continue
        body.append("    " + stripped + nl)

    new_lines = lines[:head + 1] + body + lines[tail:]
    text = "".join(new_lines)

    out = text.encode("utf-8")
    if has_bom:
        out = bom + out
    with io.open(APP, "wb") as fh:
        fh.write(out)

    py_compile.compile(APP, doraise=True)
    print("app.py branch body indented: %d lines, BOM=%s, newline=%r"
          % (len(text.splitlines()), has_bom, nl))
    print("  - sardine branch body %d..%d moved from 12 to 16 spaces"
          % (head + 2, tail))


if __name__ == "__main__":
    main()