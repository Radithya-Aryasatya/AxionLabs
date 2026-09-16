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


__all__ = [
    "solve", "_manifest_to_items", "expand_items", "score_solution",
]
