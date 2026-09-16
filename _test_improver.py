"""Probe: does solve_with_improvement() run standalone (it lazily imports app)?"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

OUT = []


def log(msg):
    OUT.append(str(msg))


manifest = [
    {"name": "BoxA", "w": 0.6, "h": 0.5, "d": 0.4, "weight": 12.0,
     "quantity": 6, "max_load": float("inf"), "sequence": 1},
    {"name": "BoxB", "w": 0.4, "h": 0.4, "d": 0.4, "weight": 6.0,
     "quantity": 8, "max_load": float("inf"), "sequence": 2},
    {"name": "Fragile1", "w": 0.5, "h": 0.3, "d": 0.3, "weight": 3.0,
     "quantity": 4, "max_load": 3.0, "sequence": 3},
]

try:
    from solver_sardine.improver import solve_with_improvement
    log("import OK")
    sol = solve_with_improvement(
        manifest, 2.4, 2.6, 6.0, 1500.0,
        budget_seconds=3.0, config={})
    log("solve_with_improvement OK")
    log("  packed=%d unfitted=%d" % (len(sol.packed), len(sol.unfitted)))
    log("  strategy=%s score=%s" % (sol.strategy, getattr(sol, "score", None)))
    log("  extra=%r" % (sol.extra,))
except Exception as e:
    log("FAIL: %r" % (e,))
    log(traceback.format_exc())

log("")
log("=== MODULE CACHE ===")
log("app imported as module: %s" % ("app" in sys.modules))

with open(os.path.join(HERE, "_test_improver_out.txt"), "w",
          encoding="utf-8") as fh:
    fh.write("\n".join(OUT) + "\n")
