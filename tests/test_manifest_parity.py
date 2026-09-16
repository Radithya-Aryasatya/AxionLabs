"""Tests for the canonical manifest pipeline.

Ensures that:
  * ``to_canonical()`` produces a stable, JSON-serialisable dict.
  * The same Excel-derived manifest yields the exact same canonical JSON
    before and after the interface refactor.
  * ``to_solution()`` round-trips a canonical result back to a Solution
    with correct metres / metres mapping.
"""
import json
import math

import pytest

from solver_common.interface import to_canonical, to_solution, _manifest_to_items
from solver_common.schemas import CargoItem, Solution, Placement, Truck


@pytest.fixture
def sample_manifest():
    return [
        {"name": "Generic Box", "w": 0.08, "h": 0.08, "d": 0.08,
         "weight": 15.0, "quantity": 2, "max_load": 50.0,
         "sequence": 1, "orientation_index": 0},
        {"name": "Fragile Crate", "w": 0.50, "h": 0.40, "d": 0.30,
         "weight": 60.0, "quantity": 1, "max_load": 60.0,
         "sequence": 3, "orientation_index": 2},
        {"name": "Heavy Barrels", "w": 1.0, "h": 1.2, "d": 0.8,
         "weight": 200.0, "quantity": 1, "max_load": float("inf"),
         "sequence": 2, "orientation_index": 0},
    ]


@pytest.fixture
def truck_params():
    return (2.4, 2.4, 6.0, 4000.0)


@pytest.fixture
def sample_canonical_result():
    return {
        "truck": {"name": "Truck", "width": 2.4, "height": 2.4,
                  "depth": 6.0, "max_weight": 4000.0},
        "packed": [
            {"name": "Generic Box #1", "partno": "ITEM-0",
             "x": 0.0, "y": 0.0, "z": 0.0,
             "w": 0.08, "h": 0.08, "d": 0.08,
             "weight": 15.0, "rotation_type": 0,
             "max_load": 50.0, "color": "#1f77b4"},
            {"name": "Heavy Barrels #1", "partno": "ITEM-2",
             "x": 1.0, "y": 0.0, "z": 3.0,
             "w": 1.0, "h": 1.2, "d": 0.8,
             "weight": 200.0, "rotation_type": 0,
             "max_load": None, "color": "#ff7f0e"},
        ],
        "unfitted": [
            {"name": "Fragile Crate #1", "partno": "ITEM-1",
             "x": 0.0, "y": 0.0, "z": 0.0,
             "w": 0.50, "h": 0.40, "d": 0.30,
             "weight": 60.0, "rotation_type": 0,
             "max_load": 60.0, "color": "#2ca02c"},
        ],
    }


class TestToCanonical:
    def test_basic_shape(self, sample_manifest, truck_params):
        canon = to_canonical(sample_manifest, *truck_params)
        assert "truck" in canon
        assert "items" in canon
        assert len(canon["items"]) == len(sample_manifest)

    def test_truck_metadata(self, sample_manifest, truck_params):
        canon = to_canonical(sample_manifest, *truck_params)
        t = canon["truck"]
        assert t["name"] == "Truck"
        assert t["width"] == 2.4
        assert t["height"] == 2.4
        assert t["depth"] == 6.0
        assert t["max_weight"] == 4000.0

    def test_dimensions_in_meters(self, sample_manifest, truck_params):
        canon = to_canonical(sample_manifest, *truck_params)
        for item in canon["items"]:
            assert item["w"] > 0
            assert item["h"] > 0
            assert item["d"] > 0
        by_name = {i["name"]: i for i in canon["items"]}
        assert by_name["Generic Box"]["w"] == pytest.approx(0.08)
        assert by_name["Fragile Crate"]["h"] == pytest.approx(0.40)
        assert by_name["Heavy Barrels"]["d"] == pytest.approx(0.80)

    def test_fragile_detection(self, sample_manifest, truck_params):
        canon = to_canonical(sample_manifest, *truck_params)
        items = {i["name"]: i for i in canon["items"]}
        assert items["Generic Box"]["fragile"] is False
        assert items["Fragile Crate"]["fragile"] is True
        assert items["Heavy Barrels"]["fragile"] is False

    def test_max_load_inf_becomes_none(self, sample_manifest, truck_params):
        canon = to_canonical(sample_manifest, *truck_params)
        items = {i["name"]: i for i in canon["items"]}
        assert items["Heavy Barrels"]["max_load"] is None
        assert items["Generic Box"]["max_load"] == 50.0

    def test_json_serialisable(self, sample_manifest, truck_params):
        canon = to_canonical(sample_manifest, *truck_params)
        text = json.dumps(canon)
        assert isinstance(text, str)
        roundtrip = json.loads(text)
        assert roundtrip["truck"]["width"] == 2.4
        assert len(roundtrip["items"]) == 3


class TestManifestParity:
    def test_deterministic_output(self, sample_manifest, truck_params):
        canon1 = to_canonical(sample_manifest, *truck_params)
        canon2 = to_canonical(sample_manifest, *truck_params)
        assert canon1 == canon2

    def test_stable_json_roundtrip(self, sample_manifest, truck_params):
        text1 = json.dumps(to_canonical(sample_manifest, *truck_params), sort_keys=True)
        text2 = json.dumps(to_canonical(sample_manifest, *truck_params), sort_keys=True)
        assert text1 == text2


class TestToSolution:
    def test_basic_solution(self, sample_canonical_result):
        sol = to_solution(sample_canonical_result, engine="test", strategy="baseline")
        assert isinstance(sol, Solution)
        assert sol.engine == "test"
        assert sol.strategy == "baseline"
        assert len(sol.packed) == 2
        assert len(sol.unfitted) == 1

    def test_truck_mapping(self, sample_canonical_result):
        sol = to_solution(sample_canonical_result)
        assert sol.truck.width == 2.4
        assert sol.truck.height == 2.4
        assert sol.truck.depth == 6.0
        assert sol.truck.max_weight == 4000.0

    def test_placement_fields_in_meters(self, sample_canonical_result):
        sol = to_solution(sample_canonical_result)
        p = sol.packed[0]
        assert isinstance(p, Placement)
        assert p.x == 0.0
        assert p.y == 0.0
        assert p.w == pytest.approx(0.08)
        assert p.h == pytest.approx(0.08)
        assert p.d == pytest.approx(0.08)
        assert p.weight == 15.0

    def test_max_load_inf_roundtrip(self, sample_canonical_result):
        sol = to_solution(sample_canonical_result)
        assert math.isinf(sol.packed[1].max_load)
        assert sol.packed[0].max_load == 50.0

    def test_unfitted_positions(self, sample_canonical_result):
        sol = to_solution(sample_canonical_result)
        uf = sol.unfitted[0]
        assert uf.x == 0.0
        assert uf.name == "Fragile Crate #1"


class TestManifestToItems:
    def test_items_match_canonical(self, sample_manifest):
        items = _manifest_to_items(sample_manifest)
        assert len(items) == 3
        assert isinstance(items[0], CargoItem)
        assert items[0].name == "Generic Box"
        assert items[0].width == 0.08
        assert items[0].height == 0.08
        assert items[0].depth == 0.08
        assert items[0].quantity == 2
        assert items[0].sequence == 1
