"""One-off repair of app.py's Sardine-Can integration block (dev-only).

The engine-selector edit left the ``if use_sardine:`` branch indented one
level too deep and dropped the classic packer's ``Packer()``/``addBin(...)``
construction, which made app.py unparseable.  This script splices the block
back together line-based (exact indentation, CRLF + BOM preserved) and guards
the classic-only packing helpers so the Sardine-Can path, which ships its own
already-packed Solution, never touches py3dbp.

Run:  python _fix_app_sardine.py
"""
import io
import os
import py_compile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")

# The engine branches, at their *correct* indentation (inside
# ``with st.spinner(...):`` whose body sits at 12 spaces).
SARDINE_IF = "            if use_sardine:"
CLASSIC_ELSE = "            else:"

# The classic py3dbp bin construction, restored to HEAD's layout.
CLASSIC_BLOCK = [
    "            else:\n",
    "                packer = Packer()\n",
    "\n",
    "                packer.addBin(\n",
    "                    Bin(\n",
    '                        "Truck",\n',
    "                        (\n",
    "                            truck_w * 100,\n",
    "                            truck_h * 100,\n",
    "                            truck_d * 100\n",
    "                          ),\n",
    "                        truck_weight\n",
    "                    )\n",
    "                )\n",
]


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

    # ── Locate the mis-indented sardine branch ────────────────────────
    head = None
    for i, ln in enumerate(lines):
        if ln.rstrip("\r\n") == "                        if use_sardine:":
            assert head is None, "duplicate mis-indented 'if use_sardine:'"
            head = i
    assert head is not None, "mis-indented 'if use_sardine:' not found"

    # The branch body runs until the de-indented classic 'else:'.
    tail = None
    for j in range(head + 1, len(lines)):
        if lines[j].rstrip("\r\n") == CLASSIC_ELSE:
            tail = j
            break
    assert tail is not None, "closing 'else:' not found after the branch"

    # ...and the classic block ends on the 16-space closing paren.
    end = None
    for k in range(tail + 1, len(lines)):
        body = lines[k].rstrip("\r\n")
        if body.strip() == ")" and _indent(body) == 16:
            end = k
            break
    assert end is not None, "closing ')' of the classic Bin(...) not found"

    # ── Rebuild the branch at the correct depth ───────────────────────
    branch = [SARDINE_IF + nl]
    for ln in lines[head + 1:tail]:
        body = ln.rstrip("\r\n")
        if body.strip() == "":
            branch.append(nl)
            continue
        assert _indent(body) >= 4, "unexpected indent in branch: %r" % body
        branch.append(body[4:] + nl)

    new_lines = lines[:head] + branch + CLASSIC_BLOCK + lines[end + 1:]
    text = "".join(new_lines)

    # ── Guard the classic-only packing helpers ────────────────────────
    # The item loader feeds py3dbp only; the Sardine-Can engine returns an
    # already-packed Solution, so the load loop must not run for it.
    old = "            counter = 0" + nl
    assert text.count(old) == 1, "counter anchor count=%d" % text.count(old)
    text = text.replace(old,
        "            # The classic loader below feeds py3dbp only — the" + nl +
        "            # Sardine-Can engine already packed the manifest inside" + nl +
        "            # solve_sardine()/solve_with_improvement(). Iterating an" + nl +
        "            # empty list therefore skips it without re-indenting the" + nl +
        "            # whole block." + nl +
        "            _classic_order = [] if use_sardine else loading_order" + nl +
        nl +
        "            counter = 0" + nl)

    old = "            for obj in loading_order:" + nl
    assert text.count(old) == 1, "loop anchor count=%d" % text.count(old)
    text = text.replace(old, "            for obj in _classic_order:" + nl)

    old = "            if prioritize_sequence:" + nl
    assert text.count(old) == 1, "pack anchor count=%d" % text.count(old)
    text = text.replace(old,
        "            if use_sardine:" + nl +
        "                # Sardine-Can applied its own ordering — including the" + nl +
        "                # soft-LIFO accessibility rule when the checkbox is on —" + nl +
        "                # inside the solver call above. pack_soft_lifo() and" + nl +
        "                # Packer.pack() exist only on the py3dbp packer." + nl +
        "                _blocked_count, _blocked_names = 0, []" + nl +
        "            elif prioritize_sequence:" + nl)

    old = "            packer.putOrder()" + nl
    assert text.count(old) == 1, "putOrder anchor count=%d" % text.count(old)
    text = text.replace(old,
        "            if not use_sardine:" + nl +
        "                packer.putOrder()" + nl)

    out = text.encode("utf-8")
    if has_bom:
        out = bom + out
    with io.open(APP, "wb") as fh:
        fh.write(out)

    py_compile.compile(APP, doraise=True)
    print("app.py repaired: %d lines, BOM=%s, newline=%r"
          % (len(text.splitlines()), has_bom, nl))
    print("  - branch restored at 12-space depth (was 24)")
    print("  - classic 'else:' block rebuilt with Packer()/addBin(Bin(...))")
    print("  - classic-only helpers guarded for the Sardine-Can path")


if __name__ == "__main__":
    main()
