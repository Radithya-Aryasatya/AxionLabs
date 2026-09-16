"""
solver_sardine.baseline
=======================
Pure-Python port of the SardineCan **Extreme Point Insertion** heuristic.

The engine consumes the *same* manifest shape that ``app.py`` builds and
returns a :class:`~solver_common.schemas.Solution` whose ``packed`` list
is converted by ``app.py`` into ``PackedItem`` objects — so the existing
3-D viewer, metrics, and fleet registration work unchanged.

Algorithm (mirrors
``SC.Core/Heuristics/PrimalHeuristic/ExtremePointInsertion.cs``):

1. **Extreme Points (EPs).** The container starts with the origin corner
   as a candidate placement point. After every successful placement the
   8 corners of the newly-placed box are added as EPs.

2. **Best-fit merit.** For each (piece, EP, rotation) combination the
   *minimum residual slack* across all three axes is computed. The
   placement with the smallest residual (tightest fit) wins.

3. **Guard rails.** Before acceptance a candidate must pass:
   bounds, collision, stability (>= 0.75 support ratio), weight,
   and the orientation rule: ``updown=False`` items may only assume
   ``RT_WHD`` (0) or ``RT_DHW`` (3) — spin on floor, never tip.

4. **Soft-LIFO (optional).** When ``prioritize_sequence`` is True items
   with a higher unloading sequence are placed first (deepest). An item
   may never be placed where an already-fitted higher-sequence box sits
   between it and the door in the same lane and shelf.

5. **EP pruning.** After each placement, EPs interior to a placed box or
   dominated by another EP are removed.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from py3dbp.constants import RotationType

from solver_common.schemas import Truck, Placement, Solution


# ──────────────────────────────────────────────────────────────────────
#  Constants
# ──────────────────────────────────────────────────────────────────────

#: Tolerance for face-to-face contact / duplicate detection (cm).
EPS = 1e-6

#: Rotations allowed for a ``updown=False`` item — spin on the floor only
#: (mirrors ``RotationType.Notupdown`` in ``py3dbp/constants.py``).
SPIN_ONLY = list(RotationType.Notupdown)

#: All six rotations (available if a caller ever unlocks tipping).
ALL_ROTATIONS = list(RotationType.ALL)

#: C# engine default support-surface ratio (``-ssr`` in SC.CLI).
DEFAULT_SUPPORT_RATIO = 0.75


# ──────────────────────────────────────────────────────────────────────
#  Geometric helpers (cm coordinates)
# ──────────────────────────────────────────────────────────────────────

def _rot_dim(w, h, d, rt):
    """Return (width, height, depth) for a given rotation type."""
    if rt == RotationType.RT_WHD:   # 0
        return w, h, d
    if rt == RotationType.RT_HWD:   # 1
        return h, w, d
    if rt == RotationType.RT_HDW:   # 2
        return h, d, w
    if rt == RotationType.RT_DHW:   # 3
        return d, h, w
    if rt == RotationType.RT_DWH:   # 4
        return d, w, h
    if rt == RotationType.RT_WDH:   # 5
        return w, d, h
    return w, h, d


def _aabb_overlap(a, b):
    """3-D AABB overlap. a/b = (x,y,z,w,h,d)."""
    ax0, ay0, az0 = a[0], a[1], a[2]
    ax1, ay1, az1 = ax0 + a[3], ay0 + a[4], az0 + a[5]
    bx0, by0, bz0 = b[0], b[1], b[2]
    bx1, by1, bz1 = bx0 + b[3], by0 + b[4], bz0 + b[5]
    return (ax0 < bx1 - EPS and bx0 < ax1 - EPS and
            ay0 < by1 - EPS and by0 < ay1 - EPS and
            az0 < bz1 - EPS and bz0 < az1 - EPS)


def _xz_overlap(a, b):
    """2-D X-Z overlap area (footprint projection)."""
    ax0, az0 = a[0], a[2]
    ax1, az1 = ax0 + a[3], az0 + a[5]
    bx0, bz0 = b[0], b[2]
    bx1, bz1 = bx0 + b[3], bz0 + b[5]
    ox = min(ax1, bx1) - max(ax0, bx0)
    oz = min(az1, bz1) - max(az0, bz0)
    return ox * oz if ox > 0 and oz > 0 else 0.0
    

# ──────────────────────────────────────────────────────────────────────
#  Stability + LIFO accessibility (ported from py3dbp Bin methods)
# ──────────────────────────────────────────────────────────────────────

def _is_supported(x, y, z, w, h, d, placed, support_ratio):
    """Stability check — same rule as ``Bin._isStableAt``.

    * y ≤ 0 → on floor, always stable.
    * Otherwise ≥ ``support_ratio`` of the footprint must be covered by the
      top faces of already-placed items directly beneath, *and* the centre
      of mass must lie on a supporter.  Below 0.25 we allow a 4-vertex fallback.
    """
    if y <= EPS:
        return True
    footprint = w * d
    if footprint <= 0:
        return True
    support_area = 0.0
    centre_ok = False
    cx = x + w / 2.0
    cz = z + d / 2.0
    for (px, py, pz, pw, ph, pd) in placed:
        if abs(y - (py + ph)) > 1e-3:
            continue
        ox = min(x + w, px + pw) - max(x, px)
        oz = min(z + d, pz + pd) - max(z, pz)
        if ox > EPS and oz > EPS:
            support_area += ox * oz
            if px <= cx <= px + pw and pz <= cz <= pz + pd:
                centre_ok = True
    ratio = support_area / footprint
    if ratio >= support_ratio:
        return centre_ok
    if ratio < 0.25:
        return False
    # 4-vertex fallback
    four = [(x, z), (x + w, z), (x, z + d), (x + w, z + d)]
    covered = [False] * 4
    for (px, py, pz, pw, ph, pd) in placed:
        if abs(y - (py + ph)) > 1e-3:
            continue
        for j, (vx, vz) in enumerate(four):
            if px <= vx <= px + pw and pz <= vz <= pz + pd:
                covered[j] = True
    if not all(covered):
        return False
    return centre_ok


def _is_accessible(x, y, z, w, h, d, seq, placed_full):
    """Soft-LIFO accessibility — copy of ``Bin._isAccessibleAt`` logic.

    Returns True unless a higher-sequence box is *in front* (closer to the
    door / higher z) in the same width lane and height shelf.
    """
    if seq is None:
        return True
    ix0 = x; ix1 = x + w
    iy0 = y; iy1 = y + h
    iz1 = z + d  # candidate's front face
    for pb in placed_full:
        oseq = pb["seq"]
        if oseq is None or float(oseq) <= float(seq):
            continue
        jx0 = pb["x"]; jx1 = jx0 + pb["w"]
        jy0 = pb["y"]; jy1 = jy0 + pb["h"]
        jz0 = pb["z"]
        if not (ix0 < jx1 - EPS and jx0 < ix1 - EPS):
            continue
        if not (iy0 < jy1 - EPS and jy0 < iy1 - EPS):
            continue
        if jz0 >= iz1 - 5e-4:
            return False
    return True


# ──────────────────────────────────────────────────────────────────────
#  Extreme-points container
# ──────────────────────────────────────────────────────────────────────

@dataclass
class _EPSet:
    """Manages the set of extreme points (candidate placement corners)."""
    width: float
    height: float
    depth: float
    points: list = field(default_factory=list)  # (x, y, z) in cm

    def init(self):
        """Seed with the container origin — the first placement corner."""
        self.points = [(0.0, 0.0, 0.0)]

    def add_corners(self, x, y, z, w, h, d):
        """Add the 8 corners of a placed box as candidate EPs."""
        for cx in (x, x + w):
            for cy in (y, y + h):
                for cz in (z, z + d):
                    self.points.append((cx, cy, cz))

    def prune(self, placed_boxes):
        """Remove EPs interior to a placed box or near-duplicated."""
        filtered = []
        for (px, py, pz) in self.points:
            interior = False
            for (bx, by, bz, bw, bh, bd) in placed_boxes:
                if (bx - EPS < px < bx + bw - EPS and
                    by - EPS < py < by + bh - EPS and
                    bz - EPS < pz < bz + bd - EPS):
                    interior = True
                    break
            if not interior:
                filtered.append((px, py, pz))
        unique = []
        for p in filtered:
            dup = False
            for u in unique:
                if (abs(p[0] - u[0]) < EPS and
                    abs(p[1] - u[1]) < EPS and
                    abs(p[2] - u[2]) < EPS):
                    dup = True
                    break
            if not dup:
                unique.append(p)
        self.points = unique


# ──────────────────────────────────────────────────────────────────────
#  Core solver
# ──────────────────────────────────────────────────────────────────────

@dataclass
class _PlacedItem:
    """Internal record of a placed item (cm coordinates)."""
    name: str
    partno: str
    x: float
    y: float
    z: float
    w: float  # width  (cm)
    h: float  # height (cm) — vertical
    d: float  # depth  (cm)
    weight: float
    rotation_type: int
    max_load: float
    seq: float | None = None
    color: str = "#1f77b4"

    def aabb(self):
        return (self.x, self.y, self.z, self.w, self.h, self.d)


def _build_items_from_manifest(manifest):
    """Expand the app.py manifest into a flat list of ``_PlacedItem``
    templates (pre-placement; each copy is a distinct object)."""
    templates = []
    for m in manifest:
        w = float(m["w"]) * 100   # m -> cm
        h = float(m["h"]) * 100
        d = float(m["d"]) * 100
        qty = int(m.get("quantity", 1))
        qty = qty if qty > 0 else 1
        for i in range(qty):
            templates.append(_PlacedItem(
                name=f'{m["name"]} #{i+1}',
                partno=f'ITEM-{m["name"]}#{i+1}',
                x=0.0, y=0.0, z=0.0,
                w=w, h=h, d=d,
                weight=float(m["weight"]),
                rotation_type=RotationType.RT_WHD,
                max_load=float(m["max_load"]) if math.isfinite(m["max_load"]) else float("inf"),
                seq=float(m["sequence"]),
                color=m.get("color", "#1f77b4"),
            ))
    return templates


def _best_fit_place(item, ep_set, bin_w, bin_h, bin_d, support_ratio,
                    max_weight, current_weight, placed_boxes, rotations,
                    allow_lifo):
    """Try every (EP, rotation); commit the best-fit (min residual).

    Returns True if placed, False otherwise.  Mutates ``placed_boxes``
    and ``ep_set``.
    """
    best_residual = None
    best_candidate = None
    for (px, py, pz) in ep_set.points:
        for rt in rotations:
            w, h, d = _rot_dim(item.w, item.h, item.d, rt)
            # Bounds check
            if (px < -EPS or py < -EPS or pz < -EPS or
                px + w > bin_w + EPS or py + h > bin_h + EPS or
                pz + d > bin_d + EPS):
                continue
            cand_aabb = (px, py, pz, w, h, d)
            # Collision check
            overlap = False
            for pb in placed_boxes:
                if _aabb_overlap(cand_aabb, pb.aabb()):
                    overlap = True
                    break
            if overlap:
                continue
            # Stability check
            floor_placed = [pb.aabb() for pb in placed_boxes]
            if not _is_supported(px, py, pz, w, h, d, floor_placed, support_ratio):
                continue
            # Weight check
            if current_weight + item.weight > max_weight:
                continue
            # Soft-LIFO accessibility
            if allow_lifo:
                placed_full = [
                    {"x": pb.x, "y": pb.y, "z": pb.z,
                     "w": pb.w, "h": pb.h, "d": pb.d, "seq": pb.seq}
                    for pb in placed_boxes
                ]
                if not _is_accessible(px, py, pz, w, h, d, item.seq,
                                      placed_full):
                    continue
            # Best-fit merit: minimum residual across all three axes
            rx = bin_w - (px + w)
            ry = bin_h - (py + h)
            rz = bin_d - (pz + d)
            residual = min(rx, ry, rz)
            if best_residual is None or residual < best_residual:
                best_residual = residual
                best_candidate = (px, py, pz, w, h, d, rt)

    if best_candidate is None:
        return False

    px, py, pz, w, h, d, rt = best_candidate
    item.x, item.y, item.z = px, py, pz
    item.w, item.h, item.d = w, h, d
    item.rotation_type = rt
    placed_boxes.append(item)
    ep_set.add_corners(px, py, pz, w, h, d)
    return True


def solve_sardine(manifest, truck_w, truck_h, truck_d, truck_weight,
                  prioritize_sequence=False,
                  support_surface_ratio=DEFAULT_SUPPORT_RATIO):
    """Run the Extreme Point Insertion heuristic.

    Parameters mirror ``solver_classic.adapter.solve``.
    """
    truck = Truck(name="Truck", width=truck_w, height=truck_h,
                  depth=truck_d, max_weight=truck_weight)

    # Work in cm internally.
    bin_w = truck_w * 100
    bin_h = truck_h * 100
    bin_d = truck_d * 100
    max_weight = truck_weight

    items = _build_items_from_manifest(manifest)

    # ── Ordering ──
    if prioritize_sequence:
        items.sort(key=lambda it: (-it.seq, -it.weight,
                                    -(it.w * it.h * it.d)))
    else:
        items.sort(key=lambda it: (
            -it.seq,
            it.max_load if math.isfinite(it.max_load) else 0,
            -(it.w * it.h * it.d),
            -it.weight,
        ))

    rotations = SPIN_ONLY  # updown=False for all items, matching app.py

    ep_set = _EPSet(width=bin_w, height=bin_h, depth=bin_d)
    ep_set.init()

    placed = []
    unfitted = []
    weight_accum = 0.0

    for item in items:
        placed_now = _best_fit_place(
            item, ep_set,
            bin_w, bin_h, bin_d,
            support_surface_ratio,
            max_weight, weight_accum,
            placed, rotations,
            allow_lifo=prioritize_sequence,
        )
        if placed_now:
            weight_accum += item.weight
            ep_set.prune([pb.aabb() for pb in placed])
        else:
            unfitted.append(item)

    # ── Build Placement list (cm -> m) ──
    packed = [
        Placement(
            name=pb.name,
            partno=pb.partno,
            x=pb.x / 100.0,
            y=pb.y / 100.0,
            z=pb.z / 100.0,
            w=pb.w / 100.0,
            h=pb.h / 100.0,
            d=pb.d / 100.0,
            weight=pb.weight,
            rotation_type=pb.rotation_type,
            max_load=pb.max_load,
            color=pb.color,
        )
        for pb in placed
    ]
    unfitted_placements = [
        Placement(
            name=u.name,
            partno=u.partno,
            x=0.0, y=0.0, z=0.0,
            w=u.w / 100.0, h=u.h / 100.0, d=u.d / 100.0,
            weight=u.weight,
            rotation_type=u.rotation_type,
            max_load=u.max_load,
            color=u.color,
        )
        for u in unfitted
    ]

    sol = Solution(
        truck=truck,
        packed=packed,
        unfitted=unfitted_placements,
        engine="sardine",
        strategy="epi-baseline",
        extra={
            "method": "ExtremePointInsertion",
            "prioritize_sequence": prioritize_sequence,
            "ep_count": len(ep_set.points),
        },
    )
    return sol


def solve(manifest, truck_w, truck_h, truck_d, truck_weight,
          prioritize_sequence=False,
          support_surface_ratio=DEFAULT_SUPPORT_RATIO,
          **kwargs):
    """Thin wrapper matching the package __init__ export convention."""
    return solve_sardine(
        manifest, truck_w, truck_h, truck_d, truck_weight,
        prioritize_sequence=prioritize_sequence,
        support_surface_ratio=support_surface_ratio,
    )





