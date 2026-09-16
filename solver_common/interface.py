"""
Common solver interface.

Every engine (Classic py3dbp, Sardine-Can AI) implements ``solve``.
The function accepts the *exact* manifest shape that ``app.py`` already
builds (``st.session_state.manifest``), the truck dimensions (in metres)
plus max weight, and the same run-options the classic code path honoured
(``prioritize_sequence`` toggles soft-LIFO).

It returns a :class:`~solver_common.schemas.Solution` whose ``packed``
list the caller converts into ``PackedItem`` objects via the shared
helpers already in ``app.py``.
"""
from dataclasses import replace
import math
import time

from .schemas import CargoItem, Truck, Placement, Solution


def _manifest_to_items(manifest) -> list[CargoItem]:
    """Convert ``app.py``'s manifest dicts into :class:`CargoItem`.

    ``manifest`` entries look like::

        {"name": str, "w": float(m), "h": float(m), "d": float(m),
         "weight": float(kg), "quantity": int, "max_load": float|inf,
         "sequence": int}

    ``w``/``h``/``d`` are already in **metres** (set by the import branch
    in ``app.py`` which divides cm by 100, or by the orientation editor).
    """
    items = []
    for idx, m in enumerate(manifest):
        items.append(CargoItem(
            name=m["name"],
            width=float(m["w"]),
            height=float(m["h"]),
            depth=float(m["d"]),
            weight=float(m["weight"]),
            max_load=m["max_load"],
            sequence=int(m["sequence"]),
            quantity=int(m.get("quantity", 1)),
            base_id=str(idx),
        ))
    return items


def solve(manifest, truck_w, truck_h, truck_d, truck_weight,
          prioritize_sequence=False,
          support_surface_ratio=0.75):
    """Default no-op engine entry — must be overridden by each adapter.

    This base implementation delegates to the classic py3dbp path so the
    package is importable even before a specific engine is plugged in.
    Concrete engines replace it by shadowing ``solver_common.interface.solve``
    with their own module, or by calling the engine modules directly.
    """
    # Imported lazily so that importing solver_common never pulls py3dbp
    # (keeps the Sardine-Can engine usable standalone).
    from solver_classic.adapter import solve as _classic
    return _classic(manifest, truck_w, truck_h, truck_d, truck_weight,
                    prioritize_sequence=prioritize_sequence,
                    support_surface_ratio=support_surface_ratio)


def expand_items(items: list[CargoItem]) -> list[CargoItem]:
    """Expand *quantities* into one CargoItem per physical unit.

    The resulting list is what the engines actually place one-by-one.
    Each copy gets a unique ``partno``-style suffix baked into a clone.
    """
    expanded = []
    for item in items:
        for i in range(item.quantity):
            expanded.append(replace(item, base_id=f"{item.base_id}#{i+1}"))
    return expanded


def score_solution(solution: Solution, truck_vol: float,
                   packed_items, manifest_lookup):
    """Compute the **same** composite score ``app.py`` uses:

    ``overall = 0.4*util + 0.4*safety + 0.2*offload``

    Delegation only — ``app.py``'s existing functions are reused so every
    engine is graded on exactly the same rubric.
    """
    from app import (calculate_utilization, calculate_load_distribution,
                     detect_floating_items, calculate_offloading_score)

    packed_m = [p for p in packed_items]
    util = calculate_utilization(packed_m, truck_vol)
    load_dist, _ = calculate_load_distribution(packed_m)
    floating_count, _ = detect_floating_items(packed_m, 0.75)
    safe_count = sum(1 for p in packed_m if load_dist[p.name] <= p.max_load)
    safety = (safe_count / len(packed_m) * 100) if packed_m else 0.0
    offload = calculate_offloading_score(packed_m, manifest_lookup)
    overall = util * 0.4 + safety * 0.4 + offload * 0.2

    solution.score = overall
    solution.extra["utilization"] = util
    solution.extra["safety_rate"] = safety
    solution.extra["offloading_score"] = offload
    solution.extra["floating_count"] = floating_count
    return overall


# ──────────────────────────────────────────────────────────────────────
#  Canonical manifest pipeline
# ──────────────────────────────────────────────────────────────────────

def to_canonical(manifest, truck_w, truck_h, truck_d, truck_weight):
    """Build a **single canonical JSON-serialisable manifest** from the
    raw ``st.session_state.manifest`` dicts.

    This is the *one* shape every engine consumes.  It normalises:
      * dimensions to **metres** (the manifest already stores metres),
      * ``max_load`` ↔ ``fragile`` (fragile ⇒ max_load = own weight),
      * truck metadata as a first-class sub-dict.

    Returns a plain ``dict`` that can be ``json.dumps``-ed without custom
    encoders (``Infinity`` is serialised as a large sentinel or via
    ``math.isinf`` check).
    """
    canonical_items = []
    for idx, m in enumerate(manifest):
        ml = m["max_load"]
        is_fragile = (
            isinstance(ml, (int, float))
            and not math.isinf(float(ml))
            and float(ml) == float(m["weight"])
        )
        canonical_items.append({
            "name": str(m["name"]),
            "w": round(float(m["w"]), 6),
            "h": round(float(m["h"]), 6),
            "d": round(float(m["d"]), 6),
            "weight": float(m["weight"]),
            "quantity": int(m.get("quantity", 1)),
            "max_load": float(ml) if math.isfinite(float(ml)) else None,
            "sequence": int(m["sequence"]),
            "fragile": bool(is_fragile),
        })
    truck_obj = {
        "name": "Truck",
        "width": round(float(truck_w), 6),
        "height": round(float(truck_h), 6),
        "depth": round(float(truck_d), 6),
        "max_weight": float(truck_weight),
    }
    return {"truck": truck_obj, "items": canonical_items}


def to_solution(canonical, engine="unknown", strategy="baseline",
                score=0.0, extra=None):
    """Convert a *canonical* result dict back into a :class:`Solution`.

    ``canonical`` has the shape::

        {
            "truck": {"width", "height", "depth", "max_weight"},
            "packed":   [ {x, y, z, w, h, d, weight, rotation_type,
                          max_load, color, name, partno}, ... ],
            "unfitted": [ ... same shape ... ],
        }

    All numeric values are in **metres** and **kg**.
    """
    t = canonical["truck"]
    truck = Truck(
        name=t.get("name", "Truck"),
        width=float(t["width"]),
        height=float(t["height"]),
        depth=float(t["depth"]),
        max_weight=float(t["max_weight"]),
    )

    def _make_placement(p):
        return Placement(
            name=p.get("name", ""),
            partno=p.get("partno", ""),
            x=float(p["x"]),
            y=float(p["y"]),
            z=float(p["z"]),
            w=float(p["w"]),
            h=float(p["h"]),
            d=float(p["d"]),
            weight=float(p["weight"]),
            rotation_type=int(p.get("rotation_type", 0)),
            max_load=(
                float("inf")
                if p.get("max_load") is None or math.isinf(float(p["max_load"]))
                else float(p["max_load"])
            ),
            color=p.get("color", "#1f77b4"),
        )

    packed = [_make_placement(p) for p in canonical.get("packed", [])]
    unfitted = [_make_placement(p) for p in canonical.get("unfitted", [])]

    return Solution(
        truck=truck,
        packed=packed,
        unfitted=unfitted,
        engine=engine,
        score=float(score),
        strategy=strategy,
        extra=dict(extra) if extra else {},
    )


def solution_to_canonical(solution):
    """Inverse of :func:`to_solution` — flatten a :class:`Solution` back into
    the plain, JSON-serialisable canonical result dict::

        {"truck": {...}, "packed": [...], "unfitted": [...]}

    Used by the round-trip tests and by any engine that wants to hand its
    raw placement list to :func:`to_solution` without leaking dataclasses.
    All numbers stay in **metres** / **kg**.
    """
    def _dump(p, placed):
        return {
            "name": p.name,
            "partno": p.partno,
            "x": float(p.x) if placed else 0.0,
            "y": float(p.y) if placed else 0.0,
            "z": float(p.z) if placed else 0.0,
            "w": float(p.w),
            "h": float(p.h),
            "d": float(p.d),
            "weight": float(p.weight),
            "rotation_type": int(p.rotation_type),
            "max_load": (None if math.isinf(float(p.max_load))
                         else float(p.max_load)),
            "color": p.color,
        }

    t = solution.truck
    return {
        "truck": {
            "name": t.name,
            "width": float(t.width),
            "height": float(t.height),
            "depth": float(t.depth),
            "max_weight": float(t.max_weight),
        },
        "packed": [_dump(p, True) for p in solution.packed],
        "unfitted": [_dump(p, False) for p in solution.unfitted],
    }


__all__ = [
    "solve", "_manifest_to_items", "expand_items", "score_solution",
    "to_canonical", "to_solution", "solution_to_canonical",
]
