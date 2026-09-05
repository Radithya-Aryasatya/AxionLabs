"""
verify_virtual_cctv.py
======================
Validation for the Virtual Rear-CCTV renderer (services/virtual_camera.py).

Proves — with no Streamlit runtime, no Gemini call and no network:
  1. The renderer produces a real PNG artifact for a Dock-1-style LIVE
     layout AND for a predetermined mock layout (assets/mock_docks/*.json)
     through the SAME code path — Docks 2-4 never depend on the worker.
  2. The fixed camera is the intended REAR / ELEVATED pose (numeric checks
     on camera metadata + the exposed projection).
  3. The rear-loading-door red strip reference is present and correctly
     oriented (pixel check inside the projected strip quad).
  4. Rendering is deterministic: re-rendering the same layout yields
     byte-identical PNG files and identical content hashes.
  5. The projection is a true perspective: the rear opening base projects
     wider and lower than the front (cab) base edge.
  6. Degenerate inputs fail gracefully (None, no crash).

Run:  python verify_virtual_cctv.py
Exit: 0 = all checks passed, 1 = at least one failure.
Artifacts are written to assets/virtual_cctv/ for human inspection.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image

from services.virtual_camera import (
    CAMERA_EYE, CAMERA_TARGET, FIT_MARGIN, FOV_V_MAX_DEG, FOV_V_MIN_DEG,
    IMAGE_SIZE, REAR_DOOR_FRAC, RENDERER_VERSION,
    layout_hash, normalize_layout, project_reference_points,
    render_virtual_cctv_file, render_virtual_cctv_for_fleet,
)

PASS, FAIL = "  PASS", "  FAIL"
results = []


def record(name, fn):
    try:
        fn()
        results.append((True, name))
        print(f"{PASS} {name}")
    except Exception as exc:
        results.append((False, name))
        print(f"{FAIL} {name}: {exc}")


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "assets", "virtual_cctv")


def build_dock1_style_layout():
    """Known packing layout shaped like the worker pipeline output:
    WHD in cm + packed_items with cm positions/dimensions (2.4x2.4x6.0 m
    truck, stepped pyramid load)."""
    s = 78.0
    items = []
    for i in range(3):
        items.append({"name": f"Pink #{i + 1}",
                      "position": [i * (s + 3), 0, 442],
                      "dimensions": [s, s, s], "color": "#e377c2"})
    for lvl in range(2):
        for i in range(3):
            items.append({"name": f"Red #{lvl * 3 + i + 1}",
                          "position": [i * (s + 3), lvl * s, 364],
                          "dimensions": [s, s, s], "color": "#d62728"})
    for i in range(3):
        items.append({"name": f"Green #{i + 1}",
                      "position": [i * (s + 3), 0, 286],
                      "dimensions": [s, s, s], "color": "#2ca02c"})
    return {"WHD": (240.0, 240.0, 600.0), "packed_items": items}


def load_mock_layout(dock_number=2):
    """Predetermined mock dock layout (the exact data Docks 2-4 use)."""
    path = os.path.join(BASE_DIR, "assets", "mock_docks",
                        f"mock_layout_dock{dock_number}.json")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    # mock_fleet_factory stores WHD in cm ((200, 200, 400) for these trucks)
    layout = {"WHD": (200.0, 200.0, 400.0),
              "packed_items": data.get("packed_items", [])}
    return layout


class _FakeFleet:
    """Duck-typed minimal Fleet (packing_layout + dock_number only)."""

    def __init__(self, layout, dock_number):
        self.packing_layout = {"layout": layout}
        self.dock_number = dock_number


def _point_in_quad(px, py, quad):
    """Ray-casting point-in-polygon for the strip quad."""
    inside = False
    n = len(quad)
    j = n - 1
    for i in range(n):
        xi, yi = quad[i]
        xj, yj = quad[j]
        if (yi > py) != (yj > py) and \
           px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _shrink(quad, factor):
    cx = sum(p[0] for p in quad) / len(quad)
    cy = sum(p[1] for p in quad) / len(quad)
    return [(cx + (x - cx) * factor, cy + (y - cy) * factor)
            for x, y in quad]


# --- 1. renderer works for Dock 1 (live) and mock Docks 2-4 alike ----------

META_A = {}


def t_renders_both_dock_sources():
    layout_a = build_dock1_style_layout()
    layout_b = load_mock_layout(2)

    path_a, meta_a = render_virtual_cctv_file(
        layout_a, os.path.join(OUT_DIR, "verify_dock1_live.png"))
    path_b, meta_b = render_virtual_cctv_file(
        layout_b, os.path.join(OUT_DIR, "verify_dock2_mock.png"))
    META_A.update(meta_a or {})

    assert path_a and os.path.exists(path_a), "Dock-1-style PNG missing"
    assert path_b and os.path.exists(path_b), "mock PNG missing"
    for path in (path_a, path_b):
        with Image.open(path) as im:
            assert im.size == IMAGE_SIZE, f"{path}: {im.size} != {IMAGE_SIZE}"

    # Same renderer, same metadata contract for both sources.
    assert set(meta_a.keys()) == set(meta_b.keys())
    assert meta_a["renderer"] == meta_b["renderer"] == RENDERER_VERSION

    # Fleet-level API (used by the Digital Twin panel) — same code path,
    # deterministic content-addressed filenames, cached on re-request.
    p1a = render_virtual_cctv_for_fleet(_FakeFleet(layout_a, 1))
    p1b = render_virtual_cctv_for_fleet(_FakeFleet(layout_a, 1))
    p2 = render_virtual_cctv_for_fleet(_FakeFleet(layout_b, 2))
    assert p1a and os.path.exists(p1a), "fleet-level render failed (Dock 1)"
    assert p2 and os.path.exists(p2), "fleet-level render failed (mock)"
    assert p1a == p1b, "fleet-level caching not deterministic"


# --- 2. fixed rear / elevated camera pose -----------------------------------

def t_camera_is_rear_elevated_perspective():
    cam = META_A["camera"]
    eye, target = cam["eye_norm"], cam["target_norm"]
    assert eye == list(CAMERA_EYE), f"eye drifted: {eye}"
    assert eye[2] > 1.0, "camera must sit OUTSIDE the rear opening (z > 1)"
    assert eye[1] > 0.5, "camera must be ELEVATED above mid-height"
    assert target[2] < 1.0 and target[2] < eye[2], \
        "camera must look INWARD (toward the cab)"
    assert cam["projection"] == "perspective"
    assert FOV_V_MIN_DEG <= cam["fov_v_deg"] <= FOV_V_MAX_DEG, \
        f"FOV out of lens range: {cam['fov_v_deg']}"
    # upward vector has no roll
    assert cam["up"] == [0.0, 1.0, 0.0]


# --- 3. red rear-loading-door strip reference, correctly oriented -----------

def t_red_strip_present_and_oriented():
    quad = META_A["strip_quad_px"]
    assert len(quad) == 4
    img = Image.open(os.path.join(
        OUT_DIR, "verify_dock1_live.png")).convert("RGB")
    w, h = img.size

    # Orientation: the NEAR edge of the strip (z = D) must project BELOW the
    # far edge (z = D - 8%) — i.e. the strip runs toward the camera.
    y_near = (quad[2][1] + quad[3][1]) / 2.0
    y_far = (quad[0][1] + quad[1][1]) / 2.0
    assert y_near > y_far, "strip near edge must sit lower in frame"
    # The strip lives in the lower part of the frame (floor at the door).
    mean_y = sum(p[1] for p in quad) / 4.0
    assert mean_y > 0.65 * h, f"strip not near the floor zone: {mean_y}/{h}"

    # Pixel proof: most pixels inside the (shrunk) quad are red-dominant.
    shrunk = _shrink(quad, 0.55)
    xs = [p[0] for p in shrunk]
    ys = [p[1] for p in shrunk]
    hits = total = 0
    for py in range(int(min(ys)), int(max(ys)) + 1):
        for px in range(int(min(xs)), int(max(xs)) + 1):
            if not _point_in_quad(px, py, shrunk):
                continue
            total += 1
            r, g, b = img.getpixel((px, py))
            if r > 70 and r > 1.5 * g and r > 1.5 * b:
                hits += 1
    assert total > 50, f"strip quad too small to sample: {total}"
    assert hits / total > 0.5, \
        f"strip not red inside its quad: {hits}/{total}"


# --- 4. determinism ----------------------------------------------------------

def t_deterministic_renders():
    layout_a = build_dock1_style_layout()
    path_1, _ = render_virtual_cctv_file(
        layout_a, os.path.join(OUT_DIR, "verify_det_1.png"))
    path_2, _ = render_virtual_cctv_file(
        layout_a, os.path.join(OUT_DIR, "verify_det_2.png"))
    with open(path_1, "rb") as f1, open(path_2, "rb") as f2:
        assert f1.read() == f2.read(), "re-render is not byte-identical"

    # Content hash is stable under item reordering and dict key order.
    shuffled = dict(layout_a)
    shuffled["packed_items"] = list(reversed(layout_a["packed_items"]))
    assert layout_hash(layout_a) == layout_hash(shuffled), \
        "layout hash must be ordering-insensitive"
    assert layout_hash(layout_a) == layout_hash(
        json.loads(json.dumps(layout_a))), \
        "layout hash must survive a JSON round-trip"

    # Provenance metadata is embedded in the artifact.
    with Image.open(path_1) as im:
        text = getattr(im, "text", {}) or {}
    assert "virtual_cctv" in text, "PNG tEXt provenance chunk missing"
    embedded = json.loads(text["virtual_cctv"])
    assert embedded["layout_hash"] == layout_hash(layout_a)
    assert embedded["renderer"] == RENDERER_VERSION


# --- 5. true perspective foreshortening --------------------------------------

def t_perspective_foreshortening():
    pts = project_reference_points(
        build_dock1_style_layout(),
        [(0, 0, 0), (1, 0, 0), (0, 0, 1), (1, 0, 1)])
    assert pts and len(pts) == 4
    front_w = abs(pts[1][0] - pts[0][0])
    rear_w = abs(pts[3][0] - pts[2][0])
    assert rear_w > front_w, \
        f"rear opening must project wider (near): {rear_w} vs {front_w}"
    rear_y = min(pts[2][1], pts[3][1])
    front_y = min(pts[0][1], pts[1][1])
    assert rear_y > front_y, "rear base edge must sit lower than the far base"
    # pose sanity: elevated eye aiming at the cargo mass
    assert CAMERA_EYE[1] == 0.72 and CAMERA_TARGET[1] == 0.34


# --- 6. graceful degradation --------------------------------------------------

def t_graceful_degradation():
    assert render_virtual_cctv_file(None, os.path.join(
        OUT_DIR, "never.png")) == (None, None)
    assert render_virtual_cctv_file({}, os.path.join(
        OUT_DIR, "never.png")) == (None, None)
    assert normalize_layout([]) is None
    assert project_reference_points({}, [(0, 0, 0)]) is None

    class _Empty:
        packing_layout = {}
        dock_number = 3
    assert render_virtual_cctv_for_fleet(_Empty()) is None

    # empty cargo but valid truck -> still renders the empty digital twin
    empty_layout = {"WHD": (200.0, 200.0, 400.0), "packed_items": []}
    path, meta = render_virtual_cctv_file(
        empty_layout, os.path.join(OUT_DIR, "verify_empty_truck.png"))
    assert path and os.path.exists(path) and meta["packed_items"] == 0


if __name__ == "__main__":
    print("=" * 64)
    print("Virtual Rear-CCTV renderer verification")
    print("=" * 64)
    record("Renders Dock-1 (live) + mock layouts via the SAME renderer",
           t_renders_both_dock_sources)
    record("Fixed camera is rear / elevated / inward perspective",
           t_camera_is_rear_elevated_perspective)
    record("Red rear-door strip present and correctly oriented",
           t_red_strip_present_and_oriented)
    record("Deterministic: byte-identical PNGs + stable content hash",
           t_deterministic_renders)
    record("True perspective foreshortening (rear > front)",
           t_perspective_foreshortening)
    record("Degenerate inputs fail gracefully", t_graceful_degradation)

    print()
    passed = sum(1 for ok, _ in results if ok)
    print(f"RESULTS: {passed}/{len(results)} passed")
    print(f"Artifacts: {OUT_DIR}")
    sys.exit(0 if passed == len(results) else 1)


