"""
solver_classic.adapter
======================
Faithful port of the **existing** py3dbp code path in ``app.py``.

This module wraps the exact ``Packer / Bin / Item`` + ``pack()`` call that
``app.py`` used *before* the solver abstraction was introduced.  It produces
byte-for-byte identical results so the classic engine is a safe default.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from py3dbp import Packer, Bin, Item
from py3dbp.constants import RotationType

from solver_common.schemas import CargoItem, Truck, Placement, Solution
from solver_common.interface import _manifest_to_items, expand_items


def _rand_color(s):
    random.seed(s)
    return "#" + "".join(random.choice("0123456789ABCDEF") for _ in range(6))


_API_COLOR_MAP = {
    1: "red", 2: "yellow", 3: "blue", 4: "green",
    5: "purple", 6: "brown", 7: "orange",
}


def _color_from_manifest(item):
    cidx = item.get("color")
    if cidx is not None and cidx in _API_COLOR_MAP:
        return _API_COLOR_MAP[cidx]
    palette = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
        "#9467bd", "#8c564b", "#e377c2", "#17becf",
        "#bcbd22", "#7f7f7f",
    ]
    cm = {}
    base = item["name"].split("#")[0].strip()
    if base not in cm:
        cm[base] = palette[len(cm) % len(palette)]
    return cm[base]


def solve(manifest, truck_w, truck_h, truck_d, truck_weight,
          prioritize_sequence=False,
          support_surface_ratio=0.75,
          number_of_decimals=3):
    """Run the **classic** py3dbp packing path.

    Parameters
    ----------
    manifest : list[dict]
        Exactly ``st.session_state.manifest`` — each dict has
        ``name, w, h, d`` (meters), ``weight``, ``quantity``,
        ``max_load`` (float|inf) and ``sequence``.
    truck_w, truck_h, truck_d : float
        Truck dimensions in **metres**.
    truck_weight : float
        Max weight in kg.
    prioritize_sequence : bool
        If True, delegate to ``pack_soft_lifo`` (LIFO enforcement)
        — mirrors the checkbox in ``app.py``.
    """
    truck = Truck(name="Truck", width=truck_w, height=truck_h,
                  depth=truck_d, max_weight=truck_weight)

    # ── Build loading priority (exact copy of app.py) ──
    loading_order = sorted(
        manifest,
        key=lambda item: (
            -item["sequence"],
            item["max_load"],
            -(item["w"] * item["h"] * item["d"]),
            -item["weight"],
        ),
    )

    # ── Construct Packer / Bin / Item (exact copy of app.py) ──
    packer = Packer()
    packer.addBin(Bin(
        "Truck",
        (truck_w * 100, truck_h * 100, truck_d * 100),
        truck_weight,
    ))

    counter = 0
    for obj in loading_order:
        for i in range(obj["quantity"]):
            packer.addItem(Item(
                partno=f"ITEM-{counter}",
                name=f'{obj["name"]} #{i+1}',
                typeof="cube",
                WHD=(
                    float(obj["w"]) * 100,
                    float(obj["h"]) * 100,
                    float(obj["d"]) * 100,
                ),
                weight=obj["weight"],
                level=1,
                loadbear=obj["max_load"],
                updown=False,
                color=_color_from_manifest(obj),
            ))
            counter += 1

    # ── Pack ──
    if prioritize_sequence:
        from app import pack_soft_lifo
        pack_soft_lifo(packer, manifest)
    else:
        packer.pack(
            bigger_first=False,
            fix_point=True,
            check_stable=True,
            support_surface_ratio=support_surface_ratio,
            number_of_decimals=number_of_decimals,
        )
        packer.putOrder()

    # ── Extract placements ──
    packed = []
    unfitted = []
    base_bin = packer.bins[0]

    for item in base_bin.items:
        pos = item.position
        dim = item.getDimension()
        packed.append(Placement(
            name=item.name,
            partno=item.partno,
            x=float(pos[0]) / 100,
            y=float(pos[1]) / 100,
            z=float(pos[2]) / 100,
            w=float(dim[0]) / 100,
            h=float(dim[1]) / 100,
            d=float(dim[2]) / 100,
            weight=float(item.weight),
            rotation_type=item.rotation_type,
            max_load=float(item.loadbear) if math.isfinite(item.loadbear) else float("inf"),
            color=item.color,
        ))

    for item in getattr(base_bin, "unfitted_items", []):
        # Unfitted items may lack a real placed orientation.
        try:
            dim = item.getDimension()
        except Exception:
            dim = [item.width, item.height, item.depth]
        unfitted.append(Placement(
            name=item.name,
            partno=item.partno,
            x=0.0, y=0.0, z=0.0,
            w=float(dim[0]) / 100,
            h=float(dim[1]) / 100,
            d=float(dim[2]) / 100,
            weight=float(item.weight),
            rotation_type=item.rotation_type,
            max_load=float(item.loadbear) if math.isfinite(item.loadbear) else float("inf"),
            color=item.color,
        ))

    sol = Solution(
        truck=truck,
        packed=packed,
        unfitted=unfitted,
        engine="classic",
        strategy="baseline",
        extra={
            "gravity": getattr(base_bin, "gravity", []),
            "prioritize_sequence": prioritize_sequence,
        },
    )
    return sol


__all__ = ["solve"]
