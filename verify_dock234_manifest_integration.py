"""verify_dock234_manifest_integration.py
=================================================
Parity regression guard for the Dock 2/3/4 digital-twins pipeline.

Background
----------
Dock 1 (Streamlit / app.py) and Docks 2/3/4 (services/dock234_engine.py) share
one py3dbp packing brain but ingest the Excel manifest independently. A
cyclic axis swap in ``dock234_engine.read_manifest_from_excel``
   w <- Length,  h <- Width,  d <- Height      (BUG)
stood every box on the wrong face. Because each SKU is a single
``sequence`` group and ``updown=False`` restricts rotations to
``Notupdown = [RT_WHD, RT_DHW]`` (no tipping), the engine cannot recover a
transposed stance at pack time. The visible effect was a hard divergence
from Dock 1: Dock 4's twin packed 255/303 (69.7%) while Dock 1 packed
303/303 (83.5%) under identical mode (sequence ON, Fuso Fighter 2.4x2.4x6.0).

Correct convention (app.py:1440-1444) is:
   width <- Width  (X),  height <- Height  (Y vertical),  depth <- Length  (Z)

This test locks that invariant in two layers:

1. AXES  : for every dock's Excel, read_manifest_from_excel emits
           w/h/d equal to (Width, Height, Length)/100 per row -- the exact
           convention app.py feeds py3dbp's WHD tuple. A cyclic
           re-introduction of the swap immediately fails here.
2. END2END: rebuilding Dock 4's twin (sequence ON) packs every SKU, i.e.
           303/303 @ 83.5% fill, 0 unfitted -- the Dock 1 golden result.

Run:  python verify_dock234_manifest_integration.py
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from services import dock234_engine as engine  # noqa: E402

MANIFEST_DIR = os.path.join(REPO_ROOT, "dock_manifests")

# Column keys the Excel reader resolves case-insensitively. These mirror the
# raw swap-folder schema and let us recompute app.py's convention by hand
# (independent of the reader under test).
COL_PACKAGE_ID = "package id"
COL_QTY = "box quantity"
COL_WEIGHT = "box weight (kg)"
COL_LENGTH = "length (cm)"
COL_WIDTH = "width (cm)"
COL_HEIGHT = "height (cm)"
COL_FRAGILE = "fragile"
COL_SEQUENCE = "unloading sequence"


def _read_raw_rows(xlsx_path):
    """Return list[dict] of the raw cm columns for each data row, keyed by
    the canonical lowercase header name. Independent of the engine."""
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb["Dock 2 - Demo"] if "Dock 2 - Demo" in wb.sheetnames else wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c).strip().lower() if c is not None else "" for c in rows[0]]
    raw = []
    for r in rows[1:]:
        d = {}
        for h, val in zip(header, r):
            d[h] = val
        raw.append(d)
    return raw


def _manifest_path(dock):
    return os.path.join(MANIFEST_DIR, f"dock{dock}_manifest.xlsx")


def test_axes_match_app_py_convention():
    """Guard against the cyclic axis swap (w<-L, h<-W, d<-H bug)."""
    for dock in (2, 3, 4):
        path = _manifest_path(dock)
        assert os.path.isfile(path), f"missing {path}"
        raw_rows = _read_raw_rows(path)
        engine_rows = engine.read_manifest_from_excel(path)
        assert len(raw_rows) == len(engine_rows), (
            f"dock {dock}: row count mismatch "
            f"raw={len(raw_rows)} engine={len(engine_rows)}"
        )
        for i, (raw, eng) in enumerate(zip(raw_rows, engine_rows)):
            # app.py convention: width<-Width, height<-Height, depth<-Length
            exp_w = float(raw[COL_WIDTH]) / 100.0
            exp_h = float(raw[COL_HEIGHT]) / 100.0
            exp_d = float(raw[COL_LENGTH]) / 100.0
            assert abs(eng["w"] - exp_w) < 1e-9, (
                f"dock {dock} row {i} ({eng['name']}): w={eng['w']} "
                f"but Width cm={raw[COL_WIDTH]} -> {exp_w}"
            )
            assert abs(eng["h"] - exp_h) < 1e-9, (
                f"dock {dock} row {i} ({eng['name']}): h={eng['h']} "
                f"but Height cm={raw[COL_HEIGHT]} -> {exp_h}"
            )
            assert abs(eng["d"] - exp_d) < 1e-9, (
                f"dock {dock} row {i} ({eng['name']}): d={eng['d']} "
                f"but Length cm={raw[COL_LENGTH]} -> {exp_d}"
            )
            # quantity + sequence must round-trip too (parity sanity)
            assert eng["quantity"] == int(raw[COL_QTY])
            assert eng["sequence"] == int(raw[COL_SEQUENCE])


def test_dock4_endtoend_golden():
    """Rebuilding Dock 4 (sequence ON) must pack 303/303 @ 83.5%, matching
    Dock 1's Fuso Fighter run. The axis bug collapsed this to 255/303.
    """
    path = _manifest_path(4)
    rows = engine.read_manifest_from_excel(path)
    layout = engine.build_layout(4, rows)
    total = layout["total_items_expected"]
    packed = layout["packed_count"]
    unfitted = layout["unfitted_count"]
    fill = layout["fill_percentage"]
    seq = layout["sequence_priority"]
    assert seq == "ON", f"dock4 sequence flag must be ON, got {seq}"
    assert packed == total, f"dock4 packed {packed}/{total} (48-box LIFO wall regression)"
    assert unfitted == 0, f"dock4 unfitted={unfitted}"
    assert fill == 83.5, f"dock4 fill {fill} != 83.5"
    # Spot-check a representative heavy/late SKU stance is upright:
    # PKG-2009 appliances (W40 H40 L70) -> [40,40,70]; crates 120 tall -> [120,120,80].
    by_id = {m["package_id"]: m for m in layout["manifest_summary"]}
    assert by_id["PKG-2009"]["dimensions"] == [40.0, 40.0, 70.0], by_id["PKG-2009"]["dimensions"]
    assert by_id["PKG-2002"]["dimensions"] == [120.0, 120.0, 80.0], by_id["PKG-2002"]["dimensions"]


def test_docks23_sane_pack_rate():
    """Docks 2/3 manifests are harder shapes than Dock 4 and do not fully
    load under strict soft-LIFO even with correct axes -- that is expected,
    NOT a regression. The axis-swap bug is fully guarded by
    test_axes_match_app_py_convention above (it asserts w/h/d ==
    Width/Height/Length per row for docks 2/3/4). Here we only assert engine
    continuity: each dock packs a non-trivial share, the LIFO ordering still
    kicks in, and the axis-corrected fill is materially above the buggy
    floor (buggy dock4 was 69.7%)."""
    for dock in (2, 3):
        rows = engine.read_manifest_from_excel(_manifest_path(dock))
        layout = engine.build_layout(dock, rows)
        total = layout["total_items_expected"]
        packed = layout["packed_count"]
        fill = layout["fill_percentage"]
        assert layout["sequence_priority"] == "ON"
        # Continuity, not a golden: >60% packed and >72% fill (buggy floor).
        assert packed / total > 0.60, f"dock {dock}: only {packed}/{total} packed"
        assert fill > 72.0, f"dock {dock}: fill {fill}% below sane floor"


def main():
    results = []
    for name, fn in [
        ("axis parity with app.py convention", test_axes_match_app_py_convention),
        ("dock4 end-to-end 303/303 @83.5%", test_dock4_endtoend_golden),
        ("docks 2/3 sane pack-rate", test_docks23_sane_pack_rate),
    ]:
        try:
            fn()
            results.append((True, name))
            print(f"  PASS  {name}")
        except AssertionError as exc:
            results.append((False, name))
            print(f"  FAIL  {name}: {exc}")
    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    print(f"\nRESULTS: {passed}/{total} passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()

