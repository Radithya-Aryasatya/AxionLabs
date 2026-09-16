"""Diagnostic: whitespace-insensitive unified diff between two files.

Usage:  python _diff_ws.py a.py b.py
Ignores all leading/trailing whitespace so a pure re-indent shows up as
"no change" and only genuine content edits remain visible.
"""
import difflib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    path = name if os.path.isabs(name) else os.path.join(HERE, name)
    text = io.open(path, encoding="utf-8-sig").read().replace("\r\n", "\n")
    return [ln.strip() for ln in text.split("\n")]


def main():
    left_name, right_name = sys.argv[1], sys.argv[2]
    left, right = load(left_name), load(right_name)
    left = [ln for ln in left if ln]
    right = [ln for ln in right if ln]
    diff = list(difflib.unified_diff(left, right, left_name, right_name,
                                     lineterm="", n=2))
    payload = "\n".join(diff) if diff else "(no content differences)"
    io.open(os.path.join(HERE, "_wsdiff.txt"), "w", encoding="utf-8").write(payload)
    sys.stdout.write(payload + "\n")
    sys.stdout.write("\n--- changed lines: %d ---\n" % len(diff))


if __name__ == "__main__":
    main()