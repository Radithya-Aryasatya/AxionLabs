"""Smoke test for the Sardine-Can engine on a synthetic manifest (dev-only).

Usage:  python _smoke_sardine.py > _smoke_out.txt 2>&1
"""
import io
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

OUT = []


def log(*parts):
    OUT.append(" ".join(str(p) for p in parts))


def check_layout(packed, tw, th, td):
    """Return (oob, overlaps) counts for a placement list (metres)."""
    oob = 0
    for p in packed:
        if (p.x < -1e-6 or p.y < -1e-6 or p.z < -1e-6 or
                p.x + p.w > tw + 1e-6 or
                p.y + p.h > th + 1e-6 or
                p.z + p.d > td + 1e-6):
            oob += 1
    boxes = [(p.x, p.y, p.z, p.w, p.h, p.d) for p in packed]
    ov = 0
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if (a[0] < b[0] + b[3] - 1e-9 and b[0] < a[0] + a[3] - 1e-9 and
                    a[1] < b[1] + b[4] - 1e-9 and b[1] < a[1] + a[4] - 1e-9 and
                    a[2] < b[2] + b[5] - 1e-9 and b[2] < a[2] + a[5] - 1e-9):
                ov += 1
    return oob, ov


MANIFEST = [
    {"name": "BoxA", "w": 0.6, "h": 0.5, "d": 0.4, "weight": 12.0,
     "quantity": 6, "max_load": float("inf"), "sequence": 1},
    {"name": "BoxB", "w": 0.4, "h": 0.4, "d": 0.4, "weight": 6.0,
     "quantity": 8, "max_load": float("inf"), "sequence": 2},
    {"name": "Fragile1", "w": 0.5, "h": 0.3, "d": 0.3, "weight": 3.0,
     "quantity": 4, "max_load": 3.0, "sequence": 3},
]
TW, TH, TD, TWGT = 2.4, 2.6, 6.0, 1500.0


def main():
    ok = True

    log("=== 1. app import path (used by improver._score) ===")
    try:
        t0 = time.time()
        import app  # noqa: F401
        log("OK   import app in %.2fs" % (time.time() - t0))
        log("     PackedItem=%r" % (getattr(app, "PackedItem", None),))
    except Exception as e:  # noqa: BLE001
        ok = False
        log("FAIL import app: %r" % (e,))
        log(traceback.format_exc())

    log("")
    log("=== 2. baseline engine ===")
    try:
        from solver_sardine.baseline import solve_sardine
        base = solve_sardine(MANIFEST, TW, TH, TD, TWGT)
        oob, ov = check_layout(base.packed, TW, TH, TD)
        log("OK   packed=%d unfitted=%d oob=%d overlaps=%d strategy=%s"
            % (len(base.packed), len(base.unfitted), oob, ov, base.strategy))
    except Exception as e:  # noqa: BLE001
        ok = False
        base = None
        log("FAIL baseline: %r" % (e,))
        log(traceback.format_exc())

    log("")
    log("=== 3. improver (AI self-improvement) ===")
    try:
        from solver_sardine.improver import solve_with_improvement
        t0 = time.time()
        sol = solve_with_improvement(
            MANIFEST, TW, TH, TD, TWGT,
            prioritize_sequence=False, budget_seconds=3.0, config={})
        dur = time.time() - t0
        oob, ov = check_layout(sol.packed, TW, TH, TD)
        log("OK   packed=%d unfitted=%d oob=%d overlaps=%d in %.2fs"
            % (len(sol.packed), len(sol.unfitted), oob, ov, dur))
        log("     strategy=%s improved=%s score=%.4f"
            % (sol.strategy, sol.extra.get("improved"),
               float(getattr(sol, "score", 0.0))))
        log("     extra keys=%s" % sorted(sol.extra.keys()))
        if base is not None and len(sol.packed) < len(base.packed):
            ok = False
            log("FAIL improver packed fewer items than baseline")
    except Exception as e:  # noqa: BLE001
        ok = False
        log("FAIL improver: %r" % (e,))
        log(traceback.format_exc())

    log("")
    log("=== 4. improver with prioritize_sequence=True (soft-LIFO) ===")
    try:
        from solver_sardine.improver import solve_with_improvement
        sol = solve_with_improvement(
            MANIFEST, TW, TH, TD, TWGT,
            prioritize_sequence=True, budget_seconds=2.0, config={})
        oob, ov = check_layout(sol.packed, TW, TH, TD)
        log("OK   packed=%d unfitted=%d oob=%d overlaps=%d"
            % (len(sol.packed), len(sol.unfitted), oob, ov))
    except Exception as e:  # noqa: BLE001
        ok = False
        log("FAIL: %r" % (e,))
        log(traceback.format_exc())

    log("")
    log("=== 5. memory persistence round-trip ===")
    try:
        from solver_sardine import memory as M
        M.ensure_dirs()
        sig = M.manifest_hash(MANIFEST, (TW, TH, TD), TWGT)
        M.record_strategy_result(sig, "volume-desc", True, 12.5)
        w = M.load_learned_weights()
        log("OK   sig=%s strategies=%s" % (sig, sorted(w.get(sig, {}).keys())))
        log("     dir=%s" % M.PROGRESS_DIR)
    except Exception as e:  # noqa: BLE001
        ok = False
        log("FAIL memory: %r" % (e,))
        log(traceback.format_exc())

    log("")
    log("=== RESULT ===")
    log("ALL CHECKS PASSED" if ok else "THERE WERE FAILURES")

    io.open(os.path.join(HERE, "_smoke_out.txt"), "w",
            encoding="utf-8").write("\n".join(OUT) + "\n")
    sys.stdout.write("\n".join(OUT) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
