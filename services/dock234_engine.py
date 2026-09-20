"""services/dock234_engine.py
=============================
A faithful PHOTOCOPY of Dock 1's packing brain, used by Docks 2/3/4.
Why a copy (not an import of app.py)? Importing app.py drags Streamlit
session-state into the build path and could mutate Dock 1's Packer/color_map.
This module is pure-Python + the SAME vendored py3dbp engine, so Dock 1 keeps
its own engine untouched. Run: python -m services.dock234_engine --dock 2 --dock 3
"""
from __future__ import annotations

import json
import os
import sys

_AXIONLABS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AXIONLABS not in sys.path:
    sys.path.insert(0, _AXIONLABS)

from py3dbp import Packer, Bin, Item  # noqa: E402
from py3dbp.constants import RotationType  # noqa: E402

TRUCK_W_M, TRUCK_H_M, TRUCK_D_M = 2.4, 2.4, 6.0
TRUCK_W, TRUCK_H, TRUCK_D = 240.0, 240.0, 600.0  # cm
MANIFEST_DIR = os.path.join(_AXIONLABS, "dock_manifests")
MOCK_DIR = os.path.join(_AXIONLABS, "assets", "mock_docks")
MAX_LOAD_FRAGILE = 10
MAX_LOAD_SOLID = 100

_COLOR_MAP: dict[str, str] = {}


def get_color(name: str) -> str:
    """Deterministic per-SKU color (same palette/order as Dock 1)."""
    palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
               "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f"]
    base_name = name.split("#")[0].strip()
    if base_name not in _COLOR_MAP:
        _COLOR_MAP[base_name] = palette[len(_COLOR_MAP) % len(palette)]
    return _COLOR_MAP[base_name]


def calculate_overlap_area(c_x, c_w, c_z, c_d, s_x, s_w, s_z, s_d) -> float:
    """2D intersection area (X-Z plane) between two footprints (app.py)."""
    x_overlap = max(0.0, min(c_x + c_w, s_x + s_w) - max(c_x, s_x))
    z_overlap = max(0.0, min(c_z + c_d, s_z + s_d) - max(c_z, s_z))
    return x_overlap * z_overlap


def calculate_utilization(items, truck_volume: float) -> float:
    if truck_volume <= 0:
        return 0.0
    used = sum(it.w * it.h * it.d for it in items)
    return (used / truck_volume) * 100.0
    return (used / truck_volume) * 100.0

def calculate_load_distribution(items):
    """Weight resting on each item + the support graph (app.py, verbatim)."""
    EPS = 1e-3
    sorted_items = sorted(items, key=lambda i: i.y, reverse=True)
    weight_on_top = {i.name: 0.0 for i in items}
    support_graph = {i.name: [] for i in items}
    for current in sorted_items:
        total_downward_force = current.weight + weight_on_top[current.name]
        supporters = []
        total_contact_area = 0.0
        for other in items:
            if other.name == current.name:
                continue
            if abs(current.y - (other.y + other.h)) < EPS:
                area = calculate_overlap_area(
                    current.x, current.w, current.z, current.d,
                    other.x, other.w, other.z, other.d,
                )
                if area > 0:
                    supporters.append((other, area))
                    total_contact_area += area
                    support_graph[other.name].append(current.name)
        if supporters and total_contact_area > 0:
            for sup, area in supporters:
                weight_on_top[sup.name] += total_downward_force * (area / total_contact_area)
    return weight_on_top, support_graph


def detect_floating_items(items, support_threshold: float = 0.75):
    """Items whose footprint is < support_threshold supported by below."""
    floating = []
    for item in items:
        if item.y == 0:
            continue  # resting on the bin floor
        footprint_area = item.w * item.d
        if footprint_area <= 0:
            continue
        supported_area = 0.0
        for other in items:
            if other.name == item.name:
                continue
            if abs(item.y - (other.y + other.h)) < 1e-3:
                supported_area += calculate_overlap_area(
                    item.x, item.w, item.z, item.d,
                    other.x, other.w, other.z, other.d,
                )
        if supported_area / footprint_area < support_threshold:
            floating.append(item.name)
    return len(floating), floating


def calculate_blocking_metrics(items, manifest_lookup):
    """Soft-LIFO diagnostics: how many packed boxes are trapped (app.py)."""
    if not items:
        return {"blocked_count": 0, "blocked_names": [], "blocked_fraction": 0.0}

    def _seq_of(name):
        m = manifest_lookup.get(name)
        if not m:
            return None
        try:
            return int(m["sequence"])
        except (KeyError, TypeError, ValueError):
            return None

    blocked_names = []
    for item in items:
        iseq = _seq_of(item.name)
        if iseq is None:
            continue
        ix0, ix1 = float(item.x), float(item.x) + float(item.w)
        iy0, iy1 = float(item.y), float(item.y) + float(item.h)
        iz1 = float(item.z) + float(item.d)
        trapped = False
        for other in items:
            if other.name == item.name:
                continue
            oseq = _seq_of(other.name)
            if oseq is None or oseq <= iseq:
                continue
            jx0 = float(other.x); jx1 = jx0 + float(other.w)
            jy0 = float(other.y); jy1 = jy0 + float(other.h)
            jz0 = float(other.z)
            if not (ix0 < jx1 and jx0 < ix1):
                continue
            if not (iy0 < jy1 and jy0 < iy1):
                continue
            if jz0 >= iz1 - 1e-9:
                trapped = True
                break
        if trapped:
            blocked_names.append(item.name)
    return {
        "blocked_count": len(blocked_names),
        "blocked_names": blocked_names,
        "blocked_fraction": float(len(blocked_names)) / float(len(items)),
    }


def score_to_stars(score: float):
    if score >= 95:
        return "★★★★★", "Excellent"
    if score >= 70:
        return "★★★★☆", "Good"
    if score >= 45:
        return "★★★☆☆", "Fair"
    if score >= 25:
        return "★★☆☆☆", "Poor"
    return "★☆☆☆☆", "Very Poor"


def calculate_offloading_score(items, manifest_lookup):
    if len(items) == 0:
        return 100.0
    metrics = calculate_blocking_metrics(items, manifest_lookup)
    return max(0.0, 100.0 - metrics["blocked_fraction"] * 100.0)


def build_loading_priority(manifest):
    return sorted(
        manifest,
        key=lambda item: (
            -item["sequence"],
            item["max_load"],
            -(item["w"] * item["h"] * item["d"]),
            -item["weight"],
        ),
    )




class _PI:
    """Lightweight stand-in that quacks like app.py's PackedItem."""
    __slots__ = ("name", "x", "y", "z", "w", "h", "d", "weight", "_max_load")

    def __init__(self, name, x, y, z, w, h, d, weight=0.0):
        self.name = name; self.x = x; self.y = y; self.z = z
        self.w = w; self.h = h; self.d = d; self.weight = weight

    @property
    def max_load(self):
        return getattr(self, "_max_load", MAX_LOAD_SOLID)

    @max_load.setter
    def max_load(self, v):
        self._max_load = v


def _geos_from_bin(bin_obj):
    """Convert a packed py3dbp bin into light _PI geos (meters)."""
    out = []
    for _it in bin_obj.items:
        _pos = _it.position
        _dim = _it.getDimension()
        out.append(_PI(
            _it.name,
            float(_pos[0]) / 100.0, float(_pos[1]) / 100.0, float(_pos[2]) / 100.0,
            float(_dim[0]) / 100.0, float(_dim[1]) / 100.0, float(_dim[2]) / 100.0,
            float(getattr(_it, "weight", 0.0)),
        ))
    return out



def pack_soft_lifo(packer, manifest):
    """Soft-LIFO packing respecting unloading sequences (app.py copy)."""
    bin_obj = packer.bins[0]
    bin_obj.formatNumbers(3)
    for _it in packer.items:
        _it.formatNumbers(3)
    packer.binding = []
    seq_of = {}
    for _it in packer.items:
        _base = _it.name.rsplit(" #", 1)[0]
        _seq = next((o["sequence"] for o in manifest if o["name"] == _base), 1)
        _seq = int(_seq)
        seq_of[id(_it)] = _seq
        _it.sequence = _seq
    seq_groups = {}
    for _it in packer.items:
        seq_groups.setdefault(seq_of[id(_it)], []).append(_it)
    _ordered = sorted(seq_groups.keys(), reverse=True)
    for _s in _ordered:
        _grp = list(seq_groups[_s])
        _grp.sort(key=lambda x: float(x.width) * float(x.height) * float(x.depth))
        _grp.sort(key=lambda x: x.loadbear, reverse=True)
        _grp.sort(key=lambda x: x.level, reverse=False)
        for _it in _grp:
            packer.pack2Bin(bin_obj, _it, True, True, 0.75, seq=_s)
    for _bin in packer.bins:
        _still = []
        for _it in _bin.items:
            if _it.updown is False and _it.rotation_type not in RotationType.Notupdown:
                try:
                    _bin.unfitted_items.append(_it)
                except AttributeError:
                    pass
            else:
                _still.append(_it)
        _bin.items = _still
    try:
        bin_obj.gravity = packer.gravityCenter(bin_obj)
    except Exception:
        pass
    manifest_lookup = {
        _it.name: next(
            (o for o in manifest if o["name"] == _it.name.rsplit(" #", 1)[0]),
            {"sequence": 1},
        )
        for _it in packer.items
    }
    _geos = _geos_from_bin(bin_obj)
    _metrics = calculate_blocking_metrics(_geos, manifest_lookup)
    return _metrics["blocked_count"], _metrics["blocked_names"]



def pack_manifest(manifest, prioritize_sequence: bool = False):
    """Pack a manifest exactly like Dock 1 / app.py and return full metrics."""
    manifest_lookup = {
        f"{item['name']} #{i + 1}": item
        for item in manifest
        for i in range(item["quantity"])
    }

    packer = Packer()
    packer.addBin(Bin("Truck", (TRUCK_W, TRUCK_H, TRUCK_D), 4000))

    counter = 0
    loading_order = build_loading_priority(manifest)
    for obj in loading_order:
        for _ in range(obj["quantity"]):
            packer.addItem(Item(
                partno=f"ITEM-{counter}",
                name=f'{obj["name"]} #{counter + 1}',
                typeof="cube",
                WHD=(float(obj["w"]) * 100.0,
                     float(obj["h"]) * 100.0,
                     float(obj["d"]) * 100.0),
                weight=obj["weight"],
                level=1,
                loadbear=obj["max_load"],
                updown=False,
                color=get_color(obj["name"]),
            ))
            counter += 1

    if prioritize_sequence:
        blocked_count, blocked_names = pack_soft_lifo(packer, manifest)
    else:
        packer.pack(
            bigger_first=False,
            fix_point=True,
            check_stable=True,
            support_surface_ratio=0.75,
            number_of_decimals=3,
        )
        packer.putOrder()
        blocked_count, blocked_names = 0, []

    truck_vol_m = float(TRUCK_W_M * TRUCK_H_M * TRUCK_D_M)
    packed_geometries = []
    packed_json = []
    by_sku = {m["name"]: m for m in manifest}
    counters = {}

    for b in packer.bins:
        for item in b.items:
            m = manifest_lookup.get(item.name) or {
                "name": item.name.rsplit(" #", 1)[0],
                "max_load": MAX_LOAD_SOLID, "sequence": 1,
                "weight": 40, "fragile": False,
                "package_id": "?", "city": "", "handling": "", "zone": "",
            }
            pos = item.position
            dim = item.getDimension()
            base = item.name.rsplit(" #", 1)[0]
            counters[base] = counters.get(base, 0) + 1
            packed_geometries.append(_PI(
                item.name,
                float(pos[0]) / 100.0, float(pos[1]) / 100.0, float(pos[2]) / 100.0,
                float(dim[0]) / 100.0, float(dim[1]) / 100.0, float(dim[2]) / 100.0,
                float(item.weight),
            ))
            packed_geometries[-1].max_load = float(
                m.get("max_load", MAX_LOAD_SOLID))
            packed_json.append({
                "name": item.name,
                "part_number": f"{m.get('package_id', '?')}-{counters[base]}",
                "position": [float(pos[0]), float(pos[1]), float(pos[2])],
                "dimensions": [float(dim[0]), float(dim[1]), float(dim[2])],
                "weight": float(item.weight),
                "fragile": bool(by_sku.get(m["name"], {}).get("fragile", False)),
                "package_id": m.get("package_id", ""),
                "zone": m.get("zone", ""),
                "sequence": int(m.get("sequence", 1)),
                "city": m.get("city", ""),
                "handling": m.get("handling", ""),
                "max_load": float(m.get("max_load", MAX_LOAD_SOLID)),
            })

    # Carry the WHY (no_space / overweight / footprint_instability) alongside
    # each rejected package so downstream reports (executive dashboard cargo
    # manifest) can bucket it correctly instead of defaulting to no_space.
    unfitted = [
        {
            "name": it.name,
            "part_number": it.partno,
            "reason": getattr(it, "rejection_reason", None) or "no_space",
            "detail": getattr(it, "rejection_detail", "") or "",
        }
        for it in packer.bins[0].unfitted_items
    ]
    utilization = calculate_utilization(packed_geometries, truck_vol_m)
    load_distribution, _ = calculate_load_distribution(packed_geometries)
    fp_lookup = {
        pi.name: next((o for o in manifest
                       if o["name"] == pi.name.rsplit(" #", 1)[0]),
                      {"sequence": 1})
        for pi in packed_geometries
    }
    offloading_score = calculate_offloading_score(packed_geometries, fp_lookup)
    floating_count, floating_names = detect_floating_items(packed_geometries, 0.75)
    safe_count = sum(1 for it in packed_geometries
                     if load_distribution.get(it.name, 0.0) <= it.max_load)
    safety_rate = (safe_count / len(packed_geometries) * 100.0) if packed_geometries else 0.0
    offloading_stars, offloading_text = score_to_stars(offloading_score)
    safety_stars, safety_text = score_to_stars(safety_rate)

    return {
        "packed_geometries": packed_geometries,
        "packed_json": packed_json,
        "unfitted": unfitted,
        "utilization": utilization,
        "safety_rate": safety_rate,
        "offloading_score": offloading_score,
        "floating_count": floating_count,
        "floating_names": floating_names,
        "blocking": calculate_blocking_metrics(packed_geometries, fp_lookup),
        "safety_stars": safety_stars,
        "safety_text": safety_text,
        "offloading_stars": offloading_stars,
        "offloading_text": offloading_text,
        "blocked_count": blocked_count,
        "blocked_names": blocked_names,
    }


def read_manifest_from_excel(xlsx_path: str):
    """Convert a swap-folder Excel into Dock-1 manifest dicts."""
    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb["Dock 2 - Demo"] if "Dock 2 - Demo" in wb.sheetnames else wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    idx = {h.lower(): i for i, h in enumerate(header)}

    def _c(*keys):
        for k in keys:
            if k in idx:
                return r[idx[k]]
        raise KeyError("missing column " + str(keys))

    out = []
    for r in rows[1:]:
        package_id = str(_c("package id"))
        description = str(_c("item description"))
        quantity = int(_c("box quantity"))
        weight = float(_c("box weight (kg)"))
        l_cm = float(_c("length (cm)"))
        w_cm = float(_c("width (cm)"))
        h_cm = float(_c("height (cm)"))
        fragile = str(_c("fragile")).strip().lower() == "yes"
        sequence = int(_c("unloading sequence"))
        city = str(_c("destination city"))
        zone = str(_c("storage zone"))
        out.append({
            "name": f"{package_id} {description}",
            "package_id": package_id,
            # Excel columns are in CM -> store METERS so pack_manifest's
            # x100 conversion (a faithful app.py photocopy) is correct.
            # Axis convention MUST match app.py: py3dbp's WHD tuple is
            # (X width, Y = vertical height, Z = depth/door-axis). Excel
            # provides Length along the truck depth (Z), so:
            #   w (X) <- Width,  h (Y) <- Height,  d (Z) <- Length.
            # The previous L/W/H cyclic swap stood every box on the wrong
            # face; with updown=False (Notupdown rotations only) the engine
            # cannot correct a transposed stance at pack time.
            "w": w_cm / 100.0, "h": h_cm / 100.0, "d": l_cm / 100.0,
            "weight": weight,
            "quantity": quantity,
            "sequence": sequence,
            "max_load": MAX_LOAD_FRAGILE if fragile else MAX_LOAD_SOLID,
            "fragile": fragile,
            "city": city, "zone": zone,
            "tracking": str(_c("tracking number")),
            "description": description,
        })
    return out


def read_sequence_flag(dock_number: int) -> bool:
    """VSCODE-only toggle for Dock-1's sequence checkbox (per dock)."""
    flag_path = os.path.join(MANIFEST_DIR, f"dock{dock_number}_sequence.txt")
    if not os.path.isfile(flag_path):
        return True
    try:
        val = open(flag_path, encoding="utf-8").read().strip().lower()
    except Exception:
        return True
    return val in ("on", "yes", "true", "1")


def _manifest_file_path(dock_number: int) -> str:
    return os.path.join(MANIFEST_DIR, f"dock{dock_number}_manifest.xlsx")


def _normalize_row(r: dict) -> dict:
    """Accept either shape: tools.read_demo_sheet rows (L/W/H, cm) or
    read_manifest_from_excel dicts (w/h/d, meters). Output: meters manifest."""
    if "L" in r:  # tools shape (cm) -> adapt
        return {
            "name": f"{r['package_id']} {r['description']}",
            "package_id": r["package_id"],
            # tools shape L/W/H (cm) -> app.py axis convention (X=Width,
            # Y=Height, Z=Length). Same fix as read_manifest_from_excel.
            "w": float(r["W"]) / 100.0, "h": float(r["H"]) / 100.0,
            "d": float(r["L"]) / 100.0,
            "weight": float(r["weight"]), "quantity": int(r["quantity"]),
            "sequence": int(r["sequence"]),
            "max_load": MAX_LOAD_FRAGILE if r["fragile"] else MAX_LOAD_SOLID,
            "fragile": bool(r["fragile"]),
            "city": r["city"], "zone": r["zone"],
            "tracking": r["tracking"], "description": r["description"],
        }
    return r  # already a meters manifest dict


def build_layout(dock_number: int, manifest):
    """Build the full twin JSON dict from a manifest/rows list + sequence flag.

    Accepts BOTH input shapes (see _normalize_row). Internally everything is
    a meters manifest identical to Dock 1's session-state manifest.
    """
    manifest = [_normalize_row(r) for r in manifest]
    sequence_on = read_sequence_flag(dock_number)
    res = pack_manifest(manifest, prioritize_sequence=sequence_on)
    packed_items = res["packed_json"]

    counters_packed = {}
    for p in packed_items:
        base = p["name"].rsplit(" #", 1)[0]
        counters_packed[base] = counters_packed.get(base, 0) + 1

    summary = []
    for m in manifest:
        n = counters_packed.get(m["name"], 0)
        summary.append({
            "name": m["name"], "package_id": m["package_id"],
            "quantity": m["quantity"], "packed": n,
            "remaining": m["quantity"] - n,
            "fragile": m["fragile"], "max_load": m["max_load"],
            "weight": m["weight"], "dimensions": [round(m["w"] * 100, 1), round(m["h"] * 100, 1), round(m["d"] * 100, 1)],
            "zone": m["zone"], "sequence": m["sequence"],
            "city": m["city"],
            "tracking": m["tracking"],
        })

    truck_vol = TRUCK_W * TRUCK_H * TRUCK_D
    packed_vol = sum(p["dimensions"][0] * p["dimensions"][1] * p["dimensions"][2]
                     for p in packed_items)
    total_expected = sum(m["quantity"] for m in manifest)

    anomalies = []
    if res["floating_count"]:
        anomalies.append({
            "anomaly_type": "UNSTABLE_LOAD",
            "severity": "WARNING",
            "affected_items": res["floating_names"][:8],
            "analysis_paragraph": f"{res['floating_count']} item(s) rest on <75% of their footprint (floating/cantilevered).",
            "recommended_actions": ["Re-stack for >=75% bottom support + center of mass supported.", "Heavy floor, fragile top."],
            "resolved": False,
        })
    if res["blocked_count"]:
        anomalies.append({
            "anomaly_type": "SOFT_LIFO_BLOCKED",
            "severity": "INFO",
            "affected_items": res["blocked_names"][:8],
            "analysis_paragraph": f"{res['blocked_count']} item(s) need moving a later-stop box to unload (soft-LIFO).",
            "recommended_actions": ["Re-pack with Sequence: ON for strict LIFO order."],
            "resolved": False,
        })

    return {
        "id": f"Fleet Monitoring | Dock {dock_number}",
        "truck_name": "Fuso Fighter",
        "truck_dimensions": [TRUCK_W_M, TRUCK_H_M, TRUCK_D_M],
        "sequence_priority": "ON" if sequence_on else "OFF",
        "fill_percentage": round(packed_vol / truck_vol * 100, 1),
        "loading_in_progress": True,
        "doors_closing": False,
        "truck_moving": False,
        "manifest": summary,
        "packed_items": packed_items,
        "manifest_summary": summary,
        "total_items_expected": total_expected,
        "packed_count": len(packed_items),
        "unfitted_count": len(res["unfitted"]),
        "unfitted_detail": list(res["unfitted"]),
        "status": "LOADING",
        "gemini_analysis": {
            "Space Volume Utilization": f"{res['utilization']:.1f}%",
            "Structural Safety Score": f"{res['safety_stars']} ({res['safety_text']})",
            "Offloading Score": f"{res['offloading_stars']} ({res['offloading_text']})",
        },
        "anomaly_history": anomalies,
        "metrics": {
            "utilization": round(res["utilization"], 2),
            "safety_rate": round(res["safety_rate"], 2),
            "offloading_score": round(res["offloading_score"], 2),
            "floating_count": res["floating_count"],
            "blocked_count": res["blocked_count"],
            "blocking": res["blocking"],
        },
    }


def build_single_dock(dock_number: int) -> bool:
    """Rebuild one dock's JSON twin from its swap-folder Excel."""
    xlsx = _manifest_file_path(dock_number)
    if not os.path.isfile(xlsx):
        return False
    try:
        rows = read_manifest_from_excel(xlsx)
        layout = build_layout(dock_number, rows)
    except Exception as exc:
        print(f"[dock234_engine] WARNING: dock{dock_number}_manifest.xlsx could "
              f"not be read ({exc}); keeping last good layout.")
        return False
    os.makedirs(MOCK_DIR, exist_ok=True)
    path = os.path.join(MOCK_DIR, f"mock_layout_dock{dock_number}.json")
    with open(path, "w") as fh:
        json.dump(layout, fh, indent=2)
    print(f"[dock234_engine] Dock {dock_number}: packed "
          f"{layout['packed_count']}/{layout['total_items_expected']} "
          f"fill {layout['fill_percentage']}% seq="
          f"{layout['sequence_priority']} -> {path}")
    return True


def main(argv=None):
    """Rebuild requested docks. Mirrors tools/build_dock_twins.main()."""
    argv = list(argv or sys.argv[1:])
    docks = []
    i = 0
    while i < len(argv):
        if argv[i] in ("--dock", "-d"):
            docks.append(int(argv[i + 1])); i += 2
        elif argv[i] == "--all":
            docks = [2, 3, 4]; i += 1
        else:
            i += 1
    if not docks:
        docks = [2, 3]
    for d in docks:
        build_single_dock(d)


if __name__ == "__main__":
    main()
