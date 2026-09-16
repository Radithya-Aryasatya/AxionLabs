"""Smoke test for solver_sardine.cli_bridge (no C# toolchain required).

Validates:
  1. canonical manifest -> SC.CLI JsonInstance encoding (axis swap, meters)
  2. a synthetic JsonSolution -> canonical result (axis swap back)
  3. to_solution() round-trip produces a valid Solution
  4. solve_via_cli() gracefully falls back to the Python baseline offline
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from solver_common.interface import to_canonical, to_solution
from solver_sardine import cli_bridge

RAW = [
    {"name": "Box A", "w": 1.0, "h": 0.5, "d": 0.8, "weight": 10.0,
     "quantity": 2, "sequence": 1, "max_load": 50.0, "fragile": False},
    {"name": "Box B", "w": 0.6, "h": 0.6, "d": 0.6, "weight": 5.0,
     "quantity": 1, "sequence": 2, "max_load": 5.0, "fragile": True},
]
TW, TH, TD, TWG = 2.4, 2.4, 6.0, 4000.0

canon = to_canonical(RAW, TW, TH, TD, TWG)
inst = cli_bridge.to_sc_manifest(canon)

# --- 1. encoding checks ------------------------------------------------
assert inst["containers"][0]["length"] == TW, inst["containers"][0]
assert inst["containers"][0]["width"] == TD, inst["containers"][0]
assert inst["containers"][0]["height"] == TH, inst["containers"][0]
assert len(inst["pieces"]) == 3, len(inst["pieces"])
p0 = inst["pieces"][0]
assert p0["cubes"][0]["length"] == 1.0   # w
assert p0["cubes"][0]["width"] == 0.8    # d
assert p0["cubes"][0]["height"] == 0.5   # h
assert p0["allowedOrientations"] == [0, 1, 2, 3]
assert p0["data"]["quantity_idx"] == "Box A#1"
assert p0["data"]["partno"] == "Box A #1"
# fragile unit -> ThisSideUp flag
pf = [p for p in inst["pieces"] if p["data"]["quantity_idx"] == "Box B#1"][0]
assert pf["flags"] == [{"flagId": 1, "flagValue": 3}], pf["flags"]
print("[1] encoding OK - axis swap, orientations, fragile flag")

# --- 2. a synthetic C# reply -> canonical result ----------------------
fake = {
    "containers": [{
        "id": 1, "length": TW, "width": TD, "height": TH,
        "assignments": [
            {"piece": 0,
             "position": {"x": 0.3, "y": 1.2, "z": 2.0, "a": 0, "b": 0, "c": 0},
             "cubes": [{"x": 0, "y": 0, "z": 0,
                        "length": 1.0, "width": 0.8, "height": 0.5}],
             "data": {"partno": "Box A #1", "quantity_idx": "Box A#1"}},
        ],
    }],
    "offload": [
        {"piece": 2,
         "cubes": [{"x": 0, "y": 0, "z": 0,
                    "length": 0.6, "width": 0.6, "height": 0.6}],
         "data": {"partno": "Box B #1", "quantity_idx": "Box B#1"}},
    ],
}
res = cli_bridge.parse_sc_solution(fake, canon)
pk = res["packed"][0]
assert pk["x"] == 0.3, pk
assert pk["y"] == 1.2, pk       # vertical <- C# z
assert pk["z"] == 2.0, pk       # front-back <- C# y
assert pk["w"] == 1.0 and pk["h"] == 0.5 and pk["d"] == 0.8, pk
assert pk["rotation_type"] == 0, pk  # length==w -> RT_WHD
assert pk["name"] == "Box A #1"
assert res["unfitted"][0]["name"] == "Box B #1"
print("[2] parse OK - inverse axis swap, rotation_type, offload")

# --- 3. to_solution round-trip ----------------------------------------
sol = to_solution(res, engine="sardine-can", strategy="epi-csharp")
assert sol.engine == "sardine-can"
assert len(sol.packed) == 1 and len(sol.unfitted) == 1
assert sol.packed[0].h == 0.5
assert sol.truck.width == TW and sol.truck.depth == TD
print("[3] to_solution OK - Solution(packed=%d, unfitted=%d)"
      % (len(sol.packed), len(sol.unfitted)))

# --- 4. offline fallback ----------------------------------------------
canon2 = dict(canon)
canon2["_raw_manifest"] = RAW
used_native, sol2 = cli_bridge.solve_via_cli(canon2)
print("[4] solve_via_cli used_native=%s engine=%s packed=%d unfitted=%d"
      % (used_native, sol2.engine, len(sol2.packed), len(sol2.unfitted)))
assert used_native is False
assert sol2.engine == "sardine-baseline"
assert len(sol2.packed) == 3

print("ALL BRIDGE CHECKS PASSED")
