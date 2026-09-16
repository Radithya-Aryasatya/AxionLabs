"""Validation harness for the pluggable solver engines (dev-only)."""
import ast
import io
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FILES = [
    "solver_common/schemas.py",
    "solver_common/interface.py",
    "solver_common/__init__.py",
    "solver_classic/adapter.py",
    "solver_classic/__init__.py",
    "solver_sardine/baseline.py",
    "solver_sardine/improver.py",
    "solver_sardine/memory.py",
    "solver_sardine/__init__.py",
]

out = []

out.append("=== SYNTAX CHECK ===")
for f in FILES:
    p = os.path.join(HERE, f)
    if not os.path.exists(p):
        out.append(f"MISSING  {f}")
        continue
    try:
        ast.parse(io.open(p, encoding="utf-8").read(), filename=p)
        out.append(f"OK       {f}")
    except SyntaxError as e:
        out.append(f"SYNTAX   {f}: line {e.lineno}: {e.msg}")

out.append("")
out.append("=== IMPORT CHECK ===")
for mod in ["solver_common", "solver_common.schemas",
            "solver_sardine.memory", "solver_sardine.baseline",
            "solver_sardine.improver", "solver_sardine"]:
    try:
        __import__(mod)
        out.append(f"OK       import {mod}")
    except Exception as e:
        out.append(f"FAIL     import {mod}: {type(e).__name__}: {e}")
        out.append(traceback.format_exc())

io.open(os.path.join(HERE, "_validate_report.txt"), "w",
        encoding="utf-8").write("\n".join(out))
print("\n".join(out))