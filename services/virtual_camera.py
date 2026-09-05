"""
services/virtual_camera.py
==========================
Virtual rear-CCTV renderer for the 3D bin-packing digital twin.

Takes an existing 3D packing layout — the SAME `packing_layout['layout']`
structure produced by the worker pipeline (Dock 1, live) and by the mock
factory (Docks 2-4, predetermined) — and renders a deterministic 2D PNG
representing what a physical CCTV camera mounted near the REAR LOADING
OPENING would see:

    3D digital twin layout  ->  fixed virtual camera  ->  rendered 2D image

This is NOT a screenshot of the Streamlit page and NOT the interactive
Plotly viewer: it is a standalone, headless, perspective render produced
with numpy + Pillow only (no new dependencies, no browser, no kaleido).

Design contract
---------------
* Coordinate convention (normalized cargo space, each axis / WHD):
    x in [0,1]  width   (side wall .. side wall)
    y in [0,1]  height  (0 = floor, 1 = ceiling)
    z in [0,1]  depth   (0 = cab / front wall, 1 = REAR LOADING OPENING)
  This matches the py3dbp convention used across the repo (x=width,
  y=height, z=depth) and the red "Rear Loading Door" floor strip drawn by
  app.py at the last 8% of depth.
* Fixed camera pose (fractions of the truck box, identical for every
  layout -> consistent renders across docks and dimensions):
    eye    = (0.50, 0.72, 1.45)  centered, elevated, just outside the rear
                                 opening looking inward
    target = (0.50, 0.34, 0.40)  cargo mass, slight downward tilt
    up     = (0, 1, 0)           no roll
  Screen "right" is deliberately flipped (world +x appears on the LEFT)
  so the width axis reads max -> 0 left-to-right, mirroring the physical
  "WIDTH 204" floor marking visible in real rear CCTV footage.
* Perspective pinhole projection. The vertical FOV is solved per render
  from the content span (all cargo corners + the rear-door strip + the
  axis reference anchors), clamped to a realistic wide-CCTV lens range
  [40, 85] degrees, with the principal point centered on the content —
  so every layout is fully visible and identically posed; the same
  layout always yields the identical FOV.
* Rear-loading-door reference retained: translucent red floor strip on
  the last 8% of depth (same rule as app.py) plus red Width/Height/Depth
  axis reference lines with tick labels (in meters, matching
  Fleet.truck_dimensions), echoing the painted markings of a real truck
  interior ("WIDTH 204" / "HEIGHT" / "DEPTH n" scales).
* Everything is deterministic: fixed constants, no RNG, stable painter's
  ordering, fixed fonts. Two renders of the same layout are byte-identical.
* The rendered PNG embeds provenance metadata (camera pose, FOV, layout
  hash, renderer version) as a tEXt chunk.

Public API
----------
  normalize_layout(layout)              -> dict | None
  render_virtual_cctv_image(layout)     -> (PIL.Image, meta) | None
  render_virtual_cctv_bytes(layout)     -> (bytes, meta) | None
  render_virtual_cctv_file(layout, out) -> (path, meta) | None
  render_virtual_cctv_for_fleet(fleet)  -> path | None   (cached on disk)
  layout_hash(layout)                   -> str
  project_reference_points(layout, pts) -> [[px, py], ...] | None
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

# --- identity / output location -------------------------------------------

RENDERER_VERSION = "virtual-rear-cctv-1.0"
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUTPUT_DIR = os.path.join(_BASE_DIR, "assets", "virtual_cctv")

# --- fixed virtual camera (normalized truck units) -------------------------

CAMERA_EYE: Tuple[float, float, float] = (0.50, 0.72, 1.45)
CAMERA_TARGET: Tuple[float, float, float] = (0.50, 0.34, 0.40)
CAMERA_UP: Tuple[float, float, float] = (0.0, 1.0, 0.0)

# Rear-loading-door floor strip: last 8% of depth (same rule as app.py).
REAR_DOOR_FRAC = 0.08

# FOV auto-fit margin: content (cargo + door strip + opening base) is kept
# within this fraction of the half-frame, leaving room for the reference
# axis labels. Clamped to a realistic wide-CCTV lens range.
FIT_MARGIN = 0.86
FOV_V_MIN_DEG = 40.0
FOV_V_MAX_DEG = 85.0

# --- output image ----------------------------------------------------------

IMAGE_SIZE = (1000, 900)   # ~10:9, matching the expected rear-view framing
SUPERSAMPLE = 2            # render at 2x, LANCZOS downscale for AA

BG_COLOR = (12, 13, 16)
STRIP_COLOR = (220, 38, 38)
STRIP_ALPHA = 0.55
AXIS_LINE_COLOR = (153, 27, 27)    # dark red reference lines
AXIS_TEXT_COLOR = (226, 232, 240)
TICK_LEN = 12                      # px at supersampled scale
EDGE_DARKEN = 0.32                 # per-face edge stroke factor
SHAPE_BRIGHT = 0.75                # flat-shading floor
SHAPE_RANGE = 0.25                 # flat-shading headlight span

# Same palette family as the worker viewer (app.py get_color) so the virtual
# view stays visually consistent with the interactive Digital Twin.
PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f",
]

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# --- small helpers ----------------------------------------------------------


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _load_font(size_px: int):
    """Deterministic per-machine font: prefer common Windows UI fonts."""
    candidates = [
        "segoeui.ttf", "arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf",
    ]
    for cand in candidates:
        try:
            return ImageFont.truetype(cand, size_px)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size_px)
    except TypeError:
        return ImageFont.load_default()


def _blend(c1, c2, t: float) -> Tuple[int, int, int]:
    return tuple(int(round(a * t + b * (1.0 - t))) for a, b in zip(c1, c2))


# --- layout normalization ---------------------------------------------------


def _resolve_whd_cm(layout: dict) -> Optional[Tuple[float, float, float]]:
    """Resolve the truck internal dimensions in cm from a layout dict.

    Live and mock layouts both store WHD in cm; this also guards against a
    layout that (mis)stores meters by checking item extents and rescaling.
    """
    items = layout.get("packed_items") or []
    raw = layout.get("WHD") or layout.get("whd")
    try:
        whd = [float(raw[0]), float(raw[1]), float(raw[2])]
    except Exception:
        whd = [0.0, 0.0, 0.0]
    if not all(w > 0 for w in whd):
        whd = [0.0, 0.0, 0.0]

    max_ext = [0.0, 0.0, 0.0]
    for it in items:
        pos = it.get("position") or [0, 0, 0]
        dim = it.get("dimensions") or [0, 0, 0]
        for k in range(3):
            try:
                max_ext[k] = max(max_ext[k], float(pos[k]) + float(dim[k]))
            except Exception:
                continue

    if all(w > 0 for w in whd):
        if any(e > w + 1e-6 for e, w in zip(max_ext, whd)):
            # Unit-mismatch guard: if items overflow the box, try m -> cm.
            if all(e <= w * 100.0 + 1e-6 for e, w in zip(max_ext, whd)):
                whd = [w * 100.0 for w in whd]
            else:  # last resort: expand to contain the cargo
                whd = [max(w, e) for w, e in zip(whd, max_ext)]
    elif any(e > 0 for e in max_ext):
        whd = list(max_ext)  # derive the box from the cargo extents
    else:
        return None
    return (float(whd[0]), float(whd[1]), float(whd[2]))


def _item_palette_map(items: List[dict]) -> Dict[str, str]:
    """Deterministic color per cargo base name (sorted -> palette index)."""
    names = sorted({
        ((it.get("name") or "ITEM").split("#")[0].strip() or "ITEM")
        for it in items
    })
    return {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(names)}


def normalize_layout(layout: dict) -> Optional[dict]:
    """Normalize a packing layout into renderer space.

    Accepts the repo-standard layout dict:
        {'WHD': (W, H, D) cm,
         'packed_items': [{'name', 'position': [x,y,z] cm,
                           'dimensions': [dx,dy,dz] cm, 'color'?, ...}]}
    (identical structure for the live Dock 1 pipeline and mock Docks 2-4).

    Returns None when the layout carries no usable geometry.
    """
    if not isinstance(layout, dict):
        return None
    whd = _resolve_whd_cm(layout)
    if whd is None:
        return None
    W, H, D = whd

    palette_map = _item_palette_map(layout.get("packed_items") or [])
    items: List[dict] = []
    for it in layout.get("packed_items") or []:
        try:
            pos = [float(v) for v in (it.get("position") or [0, 0, 0])][:3]
            dim = [float(v) for v in (it.get("dimensions") or [0, 0, 0])][:3]
        except Exception:
            continue
        if len(pos) < 3 or len(dim) < 3:
            continue
        x0, y0, z0 = pos[0] / W, pos[1] / H, pos[2] / D
        x1, y1, z1 = ((pos[0] + dim[0]) / W,
                      (pos[1] + dim[1]) / H,
                      (pos[2] + dim[2]) / D)
        # clamp into the truck box; skip degenerate slivers
        x0, x1 = sorted((min(max(x0, 0.0), 1.0), min(max(x1, 0.0), 1.0)))
        y0, y1 = sorted((min(max(y0, 0.0), 1.0), min(max(y1, 0.0), 1.0)))
        z0, z1 = sorted((min(max(z0, 0.0), 1.0), min(max(z1, 0.0), 1.0)))
        if x1 - x0 < 1e-6 or y1 - y0 < 1e-6 or z1 - z0 < 1e-6:
            continue
        color_hex = str(it.get("color") or "")
        if not _HEX_RE.match(color_hex):
            base = ((it.get("name") or "ITEM").split("#")[0].strip() or "ITEM")
            color_hex = palette_map.get(base, PALETTE[0])
        items.append({
            "name": it.get("name") or "ITEM",
            "box": (x0, y0, z0, x1, y1, z1),
            "rgb": _hex_to_rgb(color_hex),
        })

    return {
        "whd_cm": (W, H, D),
        "whd_m": (W / 100.0, H / 100.0, D / 100.0),
        "items": items,
    }


def _canonical_layout_json(layout: dict) -> str:
    whd = _resolve_whd_cm(layout) or (0.0, 0.0, 0.0)
    items = []
    for it in layout.get("packed_items") or []:
        try:
            pos = [round(float(v), 4) for v in (it.get("position") or [])][:3]
            dim = [round(float(v), 4) for v in (it.get("dimensions") or [])][:3]
        except Exception:
            continue
        items.append({
            "name": (it.get("name") or "").split("#")[0].strip(),
            "position": pos,
            "dimensions": dim,
        })
    items.sort(key=lambda d: (d["name"], d["position"], d["dimensions"]))
    return json.dumps({"whd": list(whd), "items": items},
                      sort_keys=True, separators=(",", ":"))


def layout_hash(layout: dict) -> str:
    """Stable content hash of a layout (ordering-insensitive)."""
    return hashlib.sha256(
        _canonical_layout_json(layout).encode("utf-8")).hexdigest()


def default_output_dir() -> str:
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    return _OUTPUT_DIR


# --- camera / projection ----------------------------------------------------


def _camera_basis():
    """Build the fixed look-at basis.

    right = up x forward  (deliberate flip so world +x appears on the
    screen LEFT: the width axis reads max -> 0 left-to-right, matching the
    physical 'WIDTH 204' floor marking seen in real rear CCTV footage).
    """
    eye = np.array(CAMERA_EYE, dtype=float)
    tgt = np.array(CAMERA_TARGET, dtype=float)
    up = np.array(CAMERA_UP, dtype=float)
    fwd = tgt - eye
    fwd /= np.linalg.norm(fwd)
    right = np.cross(up, fwd)
    right /= np.linalg.norm(right)
    up_c = np.cross(fwd, right)
    return eye, fwd, right, up_c


def _content_fit_points(norm: dict) -> np.ndarray:
    """FOV fit set: actual cargo corners + door strip + opening base.

    Using the real content (not a fixed abstract ROI) guarantees the cargo
    is fully visible for ANY layout, while the fixed camera pose keeps the
    viewpoint identical everywhere. The empty-truck fallback frames the
    reference axes zone.
    """
    pts = []
    for it in norm["items"]:
        x0, y0, z0, x1, y1, z1 = it["box"]
        for x in (x0, x1):
            for y in (y0, y1):
                for z in (z0, z1):
                    pts.append((x, y, z))
    z_strip = 1.0 - REAR_DOOR_FRAC
    pts.extend([(0.0, 0.0, z_strip), (1.0, 0.0, z_strip),
                (0.0, 0.0, 1.0), (1.0, 0.0, 1.0)])
    # Reference-geometry anchors so the three axes stay framed: far base
    # corners and the top of the far-left vertical (Height) edge.
    pts.extend([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)])
    if not norm["items"]:
        for x in (0.0, 1.0):
            for y in (0.0, 0.85):
                for z in (0.0, z_strip):
                    pts.append((x, y, z))
    return np.array(pts, dtype=float)


def _solve_camera(norm: dict, W: float, H: float):
    """Fixed pose + content-fitted lens + centered principal point.

    Returns (eye, fwd, right, up_c, fov_v_rad, focal, cx, cy).
    The camera pose is constant in normalized truck units; only the lens
    (clamped) and the principal point adapt to the content span, so the
    same layout always renders byte-identically.
    """
    aspect = W / float(H)
    eye, fwd, right, up_c = _camera_basis()
    pts = _content_fit_points(norm)
    d = pts - eye
    z = d @ fwd
    x_n = (d @ right) / z
    y_n = (d @ up_c) / z
    span_x = float(x_n.max() - x_n.min())
    span_y = float(y_n.max() - y_n.min())
    tan_needed = max(span_y / (2.0 * FIT_MARGIN),
                     span_x / (2.0 * FIT_MARGIN * aspect))
    tan_min = math.tan(math.radians(FOV_V_MIN_DEG) / 2.0)
    tan_max = math.tan(math.radians(FOV_V_MAX_DEG) / 2.0)
    tan_half = min(max(tan_needed, tan_min), tan_max)
    fov_v = 2.0 * math.atan(tan_half)
    focal = (H / 2.0) / tan_half
    cx = W / 2.0 + focal * float(x_n.max() + x_n.min()) / 2.0
    cy = H / 2.0 + focal * float(y_n.max() + y_n.min()) / 2.0
    return eye, fwd, right, up_c, fov_v, focal, cx, cy


def _project(points: np.ndarray, eye, fwd, right, up_c,
             focal: float, cx: float, cy: float):
    """World (N,3) -> screen (sx, sy) + camera-space depth (N,)."""
    d = points - eye
    z = d @ fwd
    sx = cx + focal * (d @ right) / z
    sy = cy - focal * (d @ up_c) / z
    return sx, sy, z


def _box_faces(box) -> List[Tuple[np.ndarray, np.ndarray]]:
    """6 quad faces (CCW-ish winding irrelevant for fill) + outward normals."""
    x0, y0, z0, x1, y1, z1 = box
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [
        ((0, 1, 2, 3), (0.0, 0.0, -1.0)),  # cab-side wall
        ((5, 4, 7, 6), (0.0, 0.0, 1.0)),   # rear / door side
        ((0, 1, 5, 4), (0.0, -1.0, 0.0)),  # bottom
        ((3, 2, 6, 7), (0.0, 1.0, 0.0)),   # top
        ((0, 3, 7, 4), (-1.0, 0.0, 0.0)),  # x0 side
        ((1, 2, 6, 5), (1.0, 0.0, 0.0)),   # x1 side
    ]
    return [(np.array([v[i] for i in quad], dtype=float),
             np.array(nrm, dtype=float)) for quad, nrm in faces]


# --- axis reference annotations ---------------------------------------------


def _fmt_m(v: float) -> str:
    return f"{v:g}"


def _axis_title_angle(p_from, p_to, force_up: bool = False) -> float:
    """Rotation (deg CCW) so a title reads along its axis segment.

    force_up  : keep bottom-to-top reading (matplotlib-style vertical labels)
    otherwise : keep left-to-right reading (never upside-down)
    """
    dx = p_to[0] - p_from[0]
    dy = p_to[1] - p_from[1]
    if (force_up and dy > 0) or (not force_up and dx < 0):
        dx, dy = -dx, -dy
    return -math.degrees(math.atan2(dy, dx))


def _rotated_text(img, center, text, font, fill, angle_deg: float):
    """Draw text centered at `center`, rotated CCW by angle_deg degrees."""
    if abs(angle_deg) < 0.5:
        ImageDraw.Draw(img).text(center, text, font=font, fill=fill,
                                 anchor="mm")
        return
    pad = int(getattr(font, "size", 12) * 0.5) + 4
    try:
        text_w = int(font.getlength(text))
    except Exception:
        text_w = int(len(text) * getattr(font, "size", 12))
    tmp = Image.new("RGBA", (text_w + pad * 2,
                             int(getattr(font, "size", 12)) + pad * 2),
                    (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((pad, pad), text, font=font, fill=fill)
    rot = tmp.rotate(angle_deg, expand=True,
                     resample=Image.Resampling.BICUBIC)
    img.paste(rot, (int(round(center[0] - rot.width / 2.0)),
                    int(round(center[1] - rot.height / 2.0))), rot)


def _draw_axis(img, draw, p_from, p_to, tick_labels, title, title_angle,
               outward, font_tick, font_title, scale,
               line_color=AXIS_LINE_COLOR, text_color=AXIS_TEXT_COLOR):
    """One red reference axis: line + ticks + labels + rotated title."""
    line_w = max(1, int(round(2 * scale)))
    tick_len = int(TICK_LEN * scale)
    draw.line([p_from, p_to], fill=line_color, width=line_w)
    dx = p_to[0] - p_from[0]
    dy = p_to[1] - p_from[1]
    ln = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / ln, dx / ln
    if nx * outward[0] + ny * outward[1] < 0:
        nx, ny = -nx, -ny
    n_ticks = len(tick_labels)
    for i, label in enumerate(tick_labels):
        t = 0.0 if n_ticks <= 1 else i / float(n_ticks - 1)
        bx, by = p_from[0] + dx * t, p_from[1] + dy * t
        draw.line([(bx, by), (bx + nx * tick_len, by + ny * tick_len)],
                  fill=line_color, width=line_w)
        draw.text((bx + nx * tick_len * 2.8, by + ny * tick_len * 2.8),
                  label, font=font_tick, fill=text_color, anchor="mm")
    mx = (p_from[0] + p_to[0]) / 2.0
    my = (p_from[1] + p_to[1]) / 2.0
    off = tick_len * 2.8 + getattr(font_title, "size", 20) * 1.5
    _rotated_text(img, (mx + nx * off, my + ny * off), title, font_title,
                  text_color, title_angle)


# --- main render ------------------------------------------------------------


def render_virtual_cctv_image(layout: dict,
                              image_size=IMAGE_SIZE,
                              supersample: int = SUPERSAMPLE):
    """Render the fixed rear-CCTV view of a packing layout.

    Returns (PIL.Image, meta) or (None, None) when the layout is unusable.
    """
    norm = normalize_layout(layout)
    if norm is None:
        return None, None

    iw, ih = int(image_size[0]), int(image_size[1])
    ss = max(1, int(supersample))
    W, H = iw * ss, ih * ss

    eye, fwd, right, up_c, fov_v, focal, cx, cy = _solve_camera(norm, W, H)

    def proj(pt3):
        sx, sy, _ = _project(np.array([pt3], dtype=float),
                             eye, fwd, right, up_c, focal, cx, cy)
        return float(sx[0]), float(sy[0])

    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # -- 1. rear-loading-door floor strip (pre-blended vs. background) -----
    strip_z0 = 1.0 - REAR_DOOR_FRAC
    strip_screen = [proj(p) for p in
                    ((0, 0, strip_z0), (1, 0, strip_z0),
                     (1, 0, 1.0), (0, 0, 1.0))]
    draw.polygon(strip_screen, fill=_blend(STRIP_COLOR, BG_COLOR, STRIP_ALPHA))
    strip_quad_final = [(x / ss, y / ss) for x, y in strip_screen]

    # -- 2. cargo faces (painter's algorithm, backface culled) --------------
    faces = []
    for idx, item in enumerate(norm["items"]):
        for fi, (verts, nrm) in enumerate(_box_faces(item["box"])):
            centroid = verts.mean(axis=0)
            view = eye - centroid
            if float(nrm @ view) <= 0.0:
                continue  # backface cull
            depth = float(((verts - eye) @ fwd).mean())
            vn = view / float(np.linalg.norm(view))
            shade = SHAPE_BRIGHT + SHAPE_RANGE * max(0.0, float(nrm @ vn))
            rgb = tuple(min(255, int(round(c * shade))) for c in item["rgb"])
            faces.append((depth, idx, fi, verts, rgb))
    faces.sort(key=lambda fr: (-fr[0], fr[1], fr[2]))
    edge_w = ss + 1
    for _depth, _idx, _fi, verts, rgb in faces:
        sx, sy, _z = _project(verts, eye, fwd, right, up_c, focal, cx, cy)
        poly = list(zip(sx.tolist(), sy.tolist()))
        draw.polygon(poly, fill=rgb)
        draw.line(poly + [poly[0]],
                  fill=tuple(int(round(c * EDGE_DARKEN)) for c in rgb),
                  width=edge_w, joint="curve")

    # -- 3. Width / Height / Depth reference axes ---------------------------
    # Drawn on a semi-transparent overlay: they read like the painted
    # markings of a real truck interior without obscuring the cargo.
    font_tick = _load_font(int(round(22 * ss)))
    font_title = _load_font(int(round(26 * ss)))
    w_m, h_m, d_m = norm["whd_m"]
    # Outward directions are anchored to the projected truck center so the
    # labels always fall OUTSIDE the cargo scene.
    tcx, tcy, _ = _project(np.array([(0.5, 0.5, 0.5)], dtype=float),
                           eye, fwd, right, up_c, focal, cx, cy)
    center = (float(tcx[0]), float(tcy[0]))

    def outward(mid):
        return (mid[0] - center[0], mid[1] - center[1])

    def axis_mid(a, b):
        return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    axis_line = AXIS_LINE_COLOR + (170,)
    axis_text = AXIS_TEXT_COLOR + (235,)

    # Width: rear-bottom edge; world +x maps to screen LEFT, so the axis
    # reads max-width -> 0 left-to-right, like the physical floor marking.
    wa0, wa1 = proj((0.0, 0.0, 1.0)), proj((1.0, 0.0, 1.0))
    _draw_axis(overlay, odraw, wa0, wa1,
               ["0", _fmt_m(w_m / 2.0), _fmt_m(w_m)],
               "Width", 0.0, outward(axis_mid(wa0, wa1)),
               font_tick, font_title, ss, axis_line, axis_text)
    # Height: far vertical edge on the max-x (screen-left) side — the same
    # left wall the physical HEIGHT scale is painted on, receding inward.
    ha0, ha1 = proj((1.0, 0.0, 0.0)), proj((1.0, 1.0, 0.0))
    _draw_axis(overlay, odraw, ha0, ha1,
               ["0", _fmt_m(h_m / 2.0), _fmt_m(h_m)],
               "Height", _axis_title_angle(ha0, ha1, force_up=True),
               outward(axis_mid(ha0, ha1)), font_tick, font_title, ss,
               axis_line, axis_text)
    # Depth: bottom edge on the x=0 (screen-right) side, far -> near.
    da0, da1 = proj((0.0, 0.0, 0.0)), proj((0.0, 0.0, 1.0))
    _draw_axis(overlay, odraw, da0, da1,
               ["0", _fmt_m(d_m / 2.0), _fmt_m(d_m)],
               "Depth", _axis_title_angle(da0, da1),
               outward(axis_mid(da0, da1)), font_tick, font_title, ss,
               axis_line, axis_text)

    img = img.convert("RGBA")
    img.alpha_composite(overlay)
    img = img.convert("RGB")

    # -- 5. downscale + provenance metadata ---------------------------------
    out = img.resize((iw, ih), Image.Resampling.LANCZOS).convert("RGB")
    meta = {
        "renderer": RENDERER_VERSION,
        "image_size": [iw, ih],
        "supersample": ss,
        "camera": {
            "eye_norm": list(CAMERA_EYE),
            "target_norm": list(CAMERA_TARGET),
            "up": list(CAMERA_UP),
            "fov_v_deg": round(math.degrees(fov_v), 3),
            "projection": "perspective",
            "screen_mapping": "world +x -> screen left (mirrors physical "
                              "WIDTH floor marking)",
        },
        "truck_whd_cm": [round(v, 3) for v in norm["whd_cm"]],
        "truck_whd_m": [round(v, 4) for v in norm["whd_m"]],
        "packed_items": len(norm["items"]),
        "rear_door_zone": [round(1.0 - REAR_DOOR_FRAC, 4), 1.0],
        "layout_hash": layout_hash(layout),
        "strip_quad_px": [[round(x, 2), round(y, 2)]
                          for x, y in strip_quad_final],
    }
    return out, meta


# --- public convenience API --------------------------------------------------


def render_virtual_cctv_bytes(layout: dict,
                              image_size=IMAGE_SIZE,
                              supersample: int = SUPERSAMPLE,
                              extra_meta: Optional[dict] = None):
    """Render to PNG bytes. Returns (png_bytes, meta) or (None, None)."""
    img, meta = render_virtual_cctv_image(layout, image_size, supersample)
    if img is None:
        return None, None
    if extra_meta:
        meta.update(extra_meta)
    png = PngInfo()
    png.add_text("virtual_cctv", json.dumps(meta, sort_keys=True))
    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=png)
    return buf.getvalue(), meta


def render_virtual_cctv_file(layout: dict, out_path: str,
                             image_size=IMAGE_SIZE,
                             supersample: int = SUPERSAMPLE,
                             extra_meta: Optional[dict] = None):
    """Render and write a PNG artifact. Returns (path, meta) or (None, None)."""
    data, meta = render_virtual_cctv_bytes(layout, image_size, supersample,
                                           extra_meta)
    if data is None:
        return None, None
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(data)
    return out_path, meta


def render_virtual_cctv_for_fleet(fleet, refresh: bool = False) -> Optional[str]:
    """Fleet-level entry point (Dock 1 live AND mock Docks 2-4).

    Renders `fleet.packing_layout['layout']` with the fixed rear camera and
    stores a deterministic, content-addressed PNG under
    assets/virtual_cctv/virtual_cctv_dock{N}_{hash}.png (regenerated only
    when the layout content changes). Returns the path or None.

    Streamlit-free by design so any dock source can use it.
    """
    layout = getattr(fleet, "packing_layout", None)
    layout = dict(layout.get("layout") or {}) if isinstance(layout, dict) else {}
    if not layout.get("WHD"):
        truck_dims = getattr(fleet, "truck_dimensions", None)
        if truck_dims:
            try:
                layout["WHD"] = [float(d) * 100.0 for d in truck_dims]
            except Exception:
                pass
    if not layout.get("packed_items"):
        return None
    digest = layout_hash(layout)[:12]
    dock = getattr(fleet, "dock_number", 0)
    out_path = os.path.join(default_output_dir(),
                            f"virtual_cctv_dock{dock}_{digest}.png")
    if refresh or not os.path.exists(out_path):
        written, _meta = render_virtual_cctv_file(layout, out_path)
        if written is None:
            return None
    return out_path


def project_reference_points(layout: dict, points_norm) -> Optional[list]:
    """Expose the fixed projection for validation/inspection.

    points_norm: iterable of (x, y, z) in normalized truck units.
    Returns [[sx, sy], ...] in FINAL image pixel coordinates.
    """
    norm = normalize_layout(layout)
    if norm is None:
        return None
    iw, ih = IMAGE_SIZE
    W, H = iw * SUPERSAMPLE, ih * SUPERSAMPLE
    eye, fwd, right, up_c, _fov, focal, cx, cy = _solve_camera(norm, W, H)
    sx, sy, _z = _project(np.array(list(points_norm), dtype=float),
                          eye, fwd, right, up_c, focal, cx, cy)
    return [[round(float(a) / SUPERSAMPLE, 2), round(float(b) / SUPERSAMPLE, 2)]
            for a, b in zip(sx.tolist(), sy.tolist())]






