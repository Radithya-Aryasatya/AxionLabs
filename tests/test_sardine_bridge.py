"""Tests for :mod:`solver_sardine.cli_bridge`.

The C# toolchain (``dotnet``) is NOT required for these tests: they validate
the pure-Python halves of the bridge — manifest encoding, solution parsing,
and the offline fallback to :mod:`solver_sardine.baseline`.

Axis contract under test (see ``docs/SC_CLI_CONTRACT.md``):

    AxionLabs          C# SC.CLI
    ---------          ----------
    .x              <- position.x
    .y (vertical)   <- position.z
    .z (front-back) <- position.y
    .w              <- cube.length      (C# container "length" == width)
    .h              <- cube.height      (vertical, z-up)
    .d              <- cube.width
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from solver_common.interface import to_canonical, to_solution  # noqa: E402
from solver_sardine import cli_bridge  # noqa: E402

RAW_MANIFEST = [
    {"name": "Box A", "w": 1.0, "h": 0.5, "d": 0.8, "weight": 10.0,
     "quantity": 2, "sequence": 1, "max_load": 50.0, "fragile": False},
    {"name": "Box B", "w": 0.6, "h": 0.6, "d": 0.6, "weight": 5.0,
     "quantity": 1, "sequence": 2, "max_load": 5.0, "fragile": True},
]
TRUCK_W, TRUCK_H, TRUCK_D, TRUCK_WEIGHT = 2.4, 2.4, 6.0, 4000.0

# A synthetic SC.CLI reply: one "Box A #1" placed, "Box B #1" offloaded.
FAKE_SOLUTION = {
    "containers": [{
        "id": 1,
        "length": TRUCK_W, "width": TRUCK_D, "height": TRUCK_H,
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


@pytest.fixture()
def canonical():
    return to_canonical(RAW_MANIFEST, TRUCK_W, TRUCK_H, TRUCK_D, TRUCK_WEIGHT)


# ---------------------------------------------------------------- encoding

def test_container_axes_are_rotated_to_csharp(canonical):
    """AxionLabs width/depth/height -> C# length/width/height (meters)."""
    cont = cli_bridge.to_sc_manifest(canonical)["containers"][0]
    assert cont["length"] == TRUCK_W   # x  <- width
    assert cont["width"] == TRUCK_D    # y  <- depth
    assert cont["height"] == TRUCK_H   # z  <- height
    assert cont["maxWeight"] == TRUCK_WEIGHT


def test_every_manifest_unit_becomes_a_piece(canonical):
    pieces = cli_bridge.to_sc_manifest(canonical)["pieces"]
    assert len(pieces) == 3                      # 2 x Box A + 1 x Box B
    assert [p["id"] for p in pieces] == [0, 1, 2]


def test_piece_cube_axes_and_orientations(canonical):
    p0 = cli_bridge.to_sc_manifest(canonical)["pieces"][0]
    cube = p0["cubes"][0]
    assert cube["length"] == 1.0   # <- w
    assert cube["width"] == 0.8    # <- d
    assert cube["height"] == 0.5   # <- h
    # updown=False -> spin on the floor only (height stays vertical).
    assert p0["allowedOrientations"] == [0, 1, 2, 3]
    assert p0["allowedOrientations"] == cli_bridge.ORIENTATIONS_THIS_SIDE_UP
    assert p0["forbiddenOrientations"] == []


def test_piece_ids_are_unit_unique_and_recoverable(canonical):
    pieces = cli_bridge.to_sc_manifest(canonical)["pieces"]
    idxs = [p["data"]["quantity_idx"] for p in pieces]
    assert idxs == ["Box A#1", "Box A#2", "Box B#1"]
    assert len(set(idxs)) == len(idxs)
    assert pieces[0]["data"]["partno"] == "Box A #1"


def test_fragile_item_gets_this_side_up_flag(canonical):
    pieces = cli_bridge.to_sc_manifest(canonical)["pieces"]
    frag = [p for p in pieces if p["data"]["quantity_idx"] == "Box B#1"][0]
    assert frag["flags"] == [{"flagId": cli_bridge.FLAG_THIS_SIDE_UP,
                              "flagValue": cli_bridge.FLAG_FRAGILE}]
    assert pieces[0]["flags"] == []


def test_calculation_envelope_shape(canonical):
    inst = cli_bridge.to_sc_manifest(canonical)
    calc = cli_bridge.wrap_in_calculation(
        inst, cli_bridge._sc_config(budget_seconds=12.0))
    assert set(calc) == {"configuration", "instance"}
    assert calc["configuration"]["timeLimit"] == 12.0
    assert calc["instance"] is inst
    # Budget is clamped to a positive floor so the C# TimeSpan is valid.
    assert cli_bridge._sc_config(0)["timeLimit"] == 30.0


# ----------------------------------------------------------------- parsing

def test_parse_rotates_axes_back_to_axionlabs(canonical):
    """C# (x, y, z) -> AxionLabs (x, z, y); dims -> (length, width, height)."""
    res = cli_bridge.parse_sc_solution(FAKE_SOLUTION, canonical)
    pk = res["packed"][0]
    assert pk["x"] == 0.3
    assert pk["y"] == 1.2                    # vertical  <- C# z
    assert pk["z"] == 2.0                    # front-back <- C# y
    assert pk["w"] == 1.0                    # <- cube.length
    assert pk["h"] == 0.5                    # <- cube.height
    assert pk["d"] == 0.8                    # <- cube.width
    assert pk["weight"] == 10.0              # recovered from the manifest
    assert pk["max_load"] == 50.0
    assert pk["name"] == "Box A #1"


def test_parse_maps_orientation_to_py3dbp_rotation_type(canonical):
    """spin-only orientations 0/2 -> RT_WHD (0); 1/3 -> RT_DHW (3)."""
    res = cli_bridge.parse_sc_solution(FAKE_SOLUTION, canonical)
    assert res["packed"][0]["rotation_type"] == 0   # length == item w

    rotated = dict(FAKE_SOLUTION)
    rotated["containers"] = [{
        "id": 1, "length": TRUCK_W, "width": TRUCK_D, "height": TRUCK_H,
        "assignments": [{
            "piece": 0,
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "cubes": [{"x": 0, "y": 0, "z": 0, "length": 0.8,
                       "width": 1.0, "height": 0.5}],
            "data": {"partno": "Box A #1", "quantity_idx": "Box A#1"},
        }],
    }]
    pk = cli_bridge.parse_sc_solution(rotated, canonical)["packed"][0]
    assert pk["rotation_type"] == 3                 # RT_DHW
    assert pk["w"] == 0.8 and pk["d"] == 1.0


def test_parse_collects_offloaded_pieces(canonical):
    res = cli_bridge.parse_sc_solution(FAKE_SOLUTION, canonical)
    assert [u["name"] for u in res["unfitted"]] == ["Box B #1"]
    assert res["unfitted"][0]["w"] == 0.6


def test_parse_preserves_truck_geometry(canonical):
    truck = cli_bridge.parse_sc_solution(FAKE_SOLUTION, canonical)["truck"]
    assert truck["width"] == TRUCK_W
    assert truck["height"] == TRUCK_H
    assert truck["depth"] == TRUCK_D
    assert truck["max_weight"] == TRUCK_WEIGHT


def test_parsed_result_converts_to_solution(canonical):
    """The canonical result must satisfy solver_common's Solution schema."""
    res = cli_bridge.parse_sc_solution(FAKE_SOLUTION, canonical)
    sol = to_solution(res, engine="sardine-can", strategy="epi-csharp")
    assert sol.engine == "sardine-can"
    assert len(sol.packed) == 1
    assert len(sol.unfitted) == 1
    assert sol.truck.width == TRUCK_W
    assert sol.packed[0].h == 0.5


# ---------------------------------------------------------------- fallback

def test_find_cli_returns_none_without_toolchain(monkeypatch):
    """With no env override we fall back to the shipped-binary scan."""
    monkeypatch.delenv("SC_CLI", raising=False)
    monkeypatch.delenv("SOLARINE_CLI", raising=False)
    monkeypatch.setattr(cli_bridge, "_CLI_CANDIDATES", [])
    assert cli_bridge.find_cli() is None


def test_solve_via_cli_falls_back_to_baseline(canonical, monkeypatch):
    """A missing CLI must never raise — it degrades to the Python baseline."""
    monkeypatch.setattr(cli_bridge, "find_cli", lambda: None)
    canon = dict(canonical)
    canon["_raw_manifest"] = RAW_MANIFEST
    used_native, sol = cli_bridge.solve_via_cli(canon)
    assert used_native is False
    assert sol.engine == "sardine-baseline"
    assert len(sol.packed) == 3                  # everything fits the truck
    assert sol.extra.get("fallback") is True


def test_solve_via_cli_falls_back_on_cli_error(canonical, monkeypatch):
    """A CLI that errors out also degrades gracefully (no exception)."""
    monkeypatch.setattr(cli_bridge, "find_cli", lambda: "sc-cli-not-real")
    monkeypatch.setattr(cli_bridge, "_run_cli_subprocess",
                        lambda argv, payload, timeout: (None, "boom"))
    canon = dict(canonical)
    canon["_raw_manifest"] = RAW_MANIFEST
    used_native, sol = cli_bridge.solve_via_cli(canon)
    assert used_native is False
    assert sol.engine == "sardine-baseline"


def test_solve_via_cli_uses_native_result_when_available(canonical,
                                                         monkeypatch):
    """A healthy CLI reply must be parsed and returned as the native engine."""
    monkeypatch.setattr(cli_bridge, "find_cli", lambda: "sc-cli")
    monkeypatch.setattr(cli_bridge, "_run_cli_subprocess",
                        lambda argv, payload, timeout: (FAKE_SOLUTION, ""))
    used_native, sol = cli_bridge.solve_via_cli(dict(canonical))
    assert used_native is True
    assert sol.engine == "sardine-can"
    assert sol.strategy == "epi-csharp"
    assert len(sol.packed) == 1
    assert sol.extra["cli"] is True


def test_bridge_never_reads_excel():
    """Architectural guard: the bridge must not pull in an Excel reader."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "solver_sardine", "cli_bridge.py"),
        encoding="utf-8").read()
    for banned in ("read_excel", "openpyxl", "xlrd", "pandas"):
        assert banned not in src, f"bridge must not use {banned}"


def test_meters_only_no_centimeter_scaling():
    """Architectural guard: the bridge works in meters only (no ``* 100``)."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "solver_sardine", "cli_bridge.py"),
        encoding="utf-8").read()
    assert "* 100" not in src
    assert "*100" not in src

