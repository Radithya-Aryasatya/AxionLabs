"""Temporary verification harness for the pluggable solver packages.

Usage:  python _verify_solvers.py > _verify_out.txt 2>&1
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_OUT = []


def print(*args, **kwargs):  # noqa: A001 - deliberate shadow inside harness
    _OUT.append(" ".join(str(a) for a in args))


def flush_output():
    """Write the collected log as UTF-8 next to this script."""
    path = os.path.join(HERE, "_verify_out.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(_OUT) + "\n")

FILES = [
    "solver_common/__init__.py",
    "solver_common/schemas.py",
    "solver_common/interface.py",
    "solver_classic/__init__.py",
    "solver_classic/adapter.py",
    "solver_sardine/__init__.py",
    "solver_sardine/baseline.py",
    "solver_sardine/improver.py",
    "solver_sardine/memory.py",
]


def main():
    print("=== 1. SYNTAX CHECK ===")
    ok = True
    for rel in FILES:
        path = os.path.join(HERE, rel)
        if not os.path.exists(path):
            print(f"MISSING  {rel}")
            ok = False
            continue
        try:
            src = open(path, encoding="utf-8").read()
            compile(src, path, "exec")
            print(f"OK       {rel}  ({len(src.splitlines())} lines)")
        except SyntaxError as e:
            ok = False
            print(f"SYNTAX   {rel}  line {e.lineno}: {e.msg}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"ERROR    {rel}  {e!r}")

    print()
    print("=== 2. IMPORT CHECK ===")
    for mod in ("solver_common", "solver_classic", "solver_sardine",
                "solver_sardine.baseline", "solver_sardine.improver",
                "solver_sardine.memory"):
        try:
            __import__(mod)
            print(f"OK       import {mod}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"FAIL     import {mod}: {e!r}")
            traceback.print_exc()

    print()
    print("=== 3. PACK SMOKE TEST (synthetic manifest) ===")
    try:
        from solver_sardine import solve_sardine
        from solver_classic.adapter import solve as classic_solve

        manifest = [
            {"name": "BoxA", "w": 0.6, "h": 0.5, "d": 0.4, "weight": 12.0,
             "quantity": 6, "max_load": float("inf"), "sequence": 1},
            {"name": "BoxB", "w": 0.4, "h": 0.4, "d": 0.4, "weight": 6.0,
             "quantity": 8, "max_load": float("inf"), "sequence": 2},
            {"name": "Fragile1", "w": 0.5, "h": 0.3, "d": 0.3, "weight": 3.0,
             "quantity": 4, "max_load": 3.0, "sequence": 3},
        ]
        truck = dict(truck_w=2.4, truck_h=2.6, truck_d=6.0, truck_weight=1500.0)

        cls = classic_solve(manifest, **truck)
        print(f"classic : packed={len(cls.packed)} unfitted={len(cls.unfitted)}")

        sar = solve_sardine(manifest, **truck)
        print(f"sardine : packed={len(sar.packed)} unfitted={len(sar.unfitted)}")
        print(f"          engine={sar.engine} strategy={sar.strategy}")

        tvol = truck["truck_w"] * truck["truck_h"] * truck["truck_d"]
        util = sum(p.w * p.h * p.d for p in sar.packed) / tvol * 100.0
        print(f"          sardine utilisation={util:.2f}%")

        # Overlap self-check
        boxes = [(p.x, p.y, p.z, p.w, p.h, p.d) for p in sar.packed]
        overlaps = 0
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if (a[0] < b[0] + b[3] - 1e-9 and b[0] < a[0] + a[3] - 1e-9 and
                        a[1] < b[1] + b[4] - 1e-9 and b[1] < a[1] + a[4] - 1e-9 and
                        a[2] < b[2] + b[5] - 1e-9 and b[2] < a[2] + a[5] - 1e-9):
                    overlaps += 1
        print(f"          overlap pairs = {overlaps}")

        # Bounds self-check
        out_of_bounds = 0
        for p in sar.packed:
            if (p.x < -1e-6 or p.y < -1e-6 or p.z < -1e-6 or
                    p.x + p.w > truck["truck_w"] + 1e-6 or
                    p.y + p.h > truck["truck_h"] + 1e-6 or
                    p.z + p.d > truck["truck_d"] + 1e-6):
                out_of_bounds += 1
        print(f"          out-of-bounds = {out_of_bounds}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"SMOKE FAIL: {e!r}")
        traceback.print_exc()

    print()
    print("=== RESULT ===")
    print("ALL CHECKS PASSED" if ok else "THERE WERE FAILURES")
    flush_output()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
