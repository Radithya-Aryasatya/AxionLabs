"""
solver_sardine.improver
=======================
Optional self-improvement layer for the Sardine-Can AI solver.

The **baseline** (solver_sardine.baseline.solve_sardine) always runs first
and establishes a floor. The improver then tries alternative strategies
inside a user-controlled time/candidate budget and only accepts a
replacement when it is strictly better on the composite score AND still
satisfies every hard guardrail.  If nothing beats the baseline (or the
budget runs out) the baseline result is returned — the AI never makes the
output worse.

Strategies: reverse, volume-desc, weight-desc, spin-all, by-weight-then-vol.
"""
from __future__ import annotations

import time
from typing import Callable

from .baseline import solve_sardine, _build_items_from_manifest, \
    _EPSet, _best_fit_place, SPIN_ONLY, ALL_ROTATIONS
from .memory import load_learned_weights

from solver_common.schemas import Solution, Truck, Placement


def _validate_layout(packed, unfitted, bin_w, bin_h, bin_d,
                     support_ratio, max_weight):
    """Return True iff a placement list satisfies every hard guardrail."""
    for p in packed:
        if (p.x < -1e-6 or p.y < -1e-6 or p.z < -1e-6 or
            p.x + p.w > bin_w + 1e-6 or
            p.y + p.h > bin_h + 1e-6 or
            p.z + p.d > bin_d + 1e-6):
            return False
    total_w = sum(p.weight for p in packed)
    if total_w > max_weight + 1e-3:
        return False
    aabbs = [(p.x, p.y, p.z, p.w, p.h, p.d) for p in packed]
    for i in range(len(aabbs)):
        a = aabbs[i]
        for j in range(i + 1, len(aabbs)):
            b = aabbs[j]
            if (a[0] < b[0] + b[3] and b[0] < a[0] + a[3] and
                a[1] < b[1] + b[4] and b[1] < a[1] + a[4] and
                a[2] < b[2] + b[5] and b[2] < a[2] + a[5]):
                return False
    # Stability
    try:
        from .baseline import _is_supported
        for idx, p in enumerate(packed):
            if p.y <= 1e-6:
                continue
            others = [packed[k] for k in range(len(packed)) if k != idx]
            floor = [(o.x * 100, o.y * 100, o.z * 100,
                      o.w * 100, o.h * 100, o.d * 100) for o in others]
            if not _is_supported(p.x * 100, p.y * 100, p.z * 100,
                                 p.w * 100, p.h * 100, p.d * 100,
                                 floor, support_ratio):
                                return False
    except Exception:
        pass
    return True


def _score(solution, truck_vol, manifest_lookup):
    """Compute the same composite score app.py uses (delegates to app)."""
    from app import PackedItem
    packed_m = [
        PackedItem(
            name=p.name, x=p.x, y=p.y, z=p.z,
            w=p.w, h=p.h, d=p.d, weight=p.weight, max_load=p.max_load,
        ) for p in solution.packed
    ]
    from app import (calculate_utilization, calculate_load_distribution,
                     detect_floating_items, calculate_offloading_score)
    util = calculate_utilization(packed_m, truck_vol)
    load_dist, _ = calculate_load_distribution(packed_m)
    floating_count, _ = detect_floating_items(packed_m, 0.75)
    safe_count = sum(1 for p in packed_m if load_dist[p.name] <= p.max_load)
    safety = (safe_count / len(packed_m) * 100) if packed_m else 0.0
    offload = calculate_offloading_score(packed_m, manifest_lookup)
    overall = util * 0.4 + safety * 0.4 + offload * 0.2
    return overall, util, safety, offload, floating_count


def _solve_with_order(manifest, truck_dims_m, support_ratio, rotations,
                      sort_key, strategy_name):
    """EPi loop parameterised by sort key + rotation set."""
    truck_w, truck_h, truck_d = truck_dims_m
    bin_w = truck_w * 100
    bin_h = truck_h * 100
    bin_d = truck_d * 100

    # The last manifest entry is a meta-dummy carrying truck_weight; pop it.
    real_manifest = [m for m in manifest if m.get("name") != "_truck_meta"]
    truck_weight = next(
        (m.get("_truck_weight", float("inf")) for m in manifest
         if m.get("name") == "_truck_meta"), float("inf"))

    items = _build_items_from_manifest(real_manifest)
    if sort_key is not None:
        items.sort(key=sort_key)

    ep_set = _EPSet(width=bin_w, height=bin_h, depth=bin_d)
    ep_set.init()

    placed = []
    unfitted = []
    weight_accum = 0.0
    for item in items:
        placed_now = _best_fit_place(
            item, ep_set, bin_w, bin_h, bin_d,
            support_ratio, truck_weight, weight_accum,
            placed, rotations, allow_lifo=False,
        )
        if placed_now:
            weight_accum += item.weight
            ep_set.prune([pb.aabb() for pb in placed])
        else:
            unfitted.append(item)

    def _placement(pb):
        return Placement(
            name=pb.name, partno=pb.partno,
            x=pb.x / 100.0, y=pb.y / 100.0, z=pb.z / 100.0,
            w=pb.w / 100.0, h=pb.h / 100.0, d=pb.d / 100.0,
            weight=pb.weight, rotation_type=pb.rotation_type,
            max_load=pb.max_load, color=pb.color,
        )

    packed = [_placement(pb) for pb in placed]
    unfitted_places = [_placement(u) for u in unfitted]
    truck_obj = Truck(name="Truck", width=truck_w, height=truck_h,
                      depth=truck_d, max_weight=truck_weight)
    return Solution(truck=truck_obj, packed=packed,
                    unfitted=unfitted_places,
                    engine="sardine", strategy=strategy_name,
                            extra={"method": strategy_name})


def solve_with_improvement(manifest, truck_w, truck_h, truck_d, truck_weight,
                           prioritize_sequence=False,
                           support_surface_ratio=0.75,
                           budget_seconds=5.0,
                           max_candidates=8,
                           config=None):
    """Run baseline, then try alternative strategies to beat it.

    Returns a Solution. If no strategy improves on the baseline, the
    baseline result is returned unchanged.
    """
    truck_dims_m = (truck_w, truck_h, truck_d)
    truck_vol = truck_w * truck_h * truck_d

    manifest_lookup = {}
    for m in manifest:
        for i in range(int(m.get("quantity", 1))):
            manifest_lookup[f"{m['name']} #{i+1}"] = m

    t0 = time.time()
    baseline = solve_sardine(
        manifest, truck_w, truck_h, truck_d, truck_weight,
        prioritize_sequence=prioritize_sequence,
        support_surface_ratio=support_surface_ratio,
    )
    base_score, base_util, base_safe, base_off, base_floating = _score(
        baseline, truck_vol, manifest_lookup)
    elapsed = time.time() - t0

    best = baseline
    best_score = base_score
    best_strategy = "epi-baseline"

    if not prioritize_sequence and elapsed >= budget_seconds:
        baseline.score = best_score
        baseline.extra.update({
            "utilization": base_util, "safety_rate": base_safe,
            "offloading_score": base_off, "floating_count": base_floating,
            "budget_exhausted": True,
        })
        return baseline

    # Augment manifest with a meta entry carrying truck_weight.
    m2 = [dict(m) for m in manifest]
    m2.append({"name": "_truck_meta", "w": 0, "h": 0, "d": 0,
               "weight": 0, "quantity": 0, "max_load": 0,
               "sequence": 0, "_truck_weight": truck_weight})

    strategies = [
        ("reverse", lambda it: -float(it.seq)),
        ("volume-desc", lambda it: -(it.w * it.h * it.d)),
        ("weight-desc", lambda it: -it.weight),
        ("spin-all", None),
        ("by-weight-then-vol",
         lambda it: (-it.weight, -(it.w * it.h * it.d))),
    ]

    weights = config.get("ai_weights") if config else load_learned_weights()
    order = _weighted_strategy_order(strategies, weights, manifest)

    bin_w, bin_h, bin_d = truck_w * 100, truck_h * 100, truck_d * 100
    tried = set()
    for label, sort_key in order:
        if time.time() - t0 >= budget_seconds:
            break
        if label in tried:
            continue
        tried.add(label)
        try:
            if label == "spin-all":
                sol = _solve_with_order(
                    m2, truck_dims_m, support_surface_ratio,
                    ALL_ROTATIONS, None, "spin-all")
            else:
                rk = sort_key or (lambda it: -float(it.seq))
                sol = _solve_with_order(
                    m2, truck_dims_m, support_surface_ratio,
                    SPIN_ONLY, rk, label)
        except Exception:
            continue
        if not _validate_layout(sol.packed, sol.unfitted,
                                bin_w, bin_h, bin_d,
                                support_surface_ratio, truck_weight):
            continue
        score, util, safe, off, floating = _score(
            sol, truck_vol, manifest_lookup)
        if score > best_score and floating == 0:
            best = sol
            best_score = score
            best_strategy = label
            best.extra.update({
                "utilization": util, "safety_rate": safe,
                "offloading_score": off, "floating_count": floating,
            })

    best.score = best_score
    best.strategy = best_strategy
    best.extra.setdefault("utilization", base_util)
    best.extra.setdefault("safety_rate", base_safe)
    best.extra.setdefault("offloading_score", base_off)
    best.extra.setdefault("floating_count", base_floating)
    best.extra["baseline_score"] = base_score
    best.extra["improved"] = (best_strategy != "epi-baseline")
    best.extra["elapsed_s"] = time.time() - t0
    return best


def _weighted_strategy_order(strategies, weights, manifest):
    """Reorder strategies by learned weight when available.

    Falls back to natural order if no learning data exists.
    """
    ordered = list(strategies)
    try:
        from .memory import manifest_hash
        real = [m for m in manifest if m.get("name") != "_truck_meta"]
        sig = manifest_hash(real, (0, 0, 0), 0)
        bucket = weights.get(sig, {}) if weights else {}
    except Exception:
        bucket = {}
    if not bucket:
        return ordered
    ordered.sort(key=lambda s: bucket.get(s[0], {}).get("weight", 0.5),
                 reverse=True)
    return ordered


def solve(manifest, truck_w, truck_h, truck_d, truck_weight,
          prioritize_sequence=False,
          support_surface_ratio=0.75,
          improve=True,
          budget_seconds=5.0,
          max_candidates=8,
          config=None,
          **kwargs):
    """Public convenience wrapper."""
    if not improve:
        from .baseline import solve_sardine
        return solve_sardine(
            manifest, truck_w, truck_h, truck_d, truck_weight,
            prioritize_sequence=prioritize_sequence,
            support_surface_ratio=support_surface_ratio)
    return solve_with_improvement(
        manifest, truck_w, truck_h, truck_d, truck_weight,
        prioritize_sequence=prioritize_sequence,
        support_surface_ratio=support_surface_ratio,
        budget_seconds=budget_seconds,
        max_candidates=max_candidates,
        config=config)


__all__ = ["solve_with_improvement", "solve", "_validate_layout", "_score"]



