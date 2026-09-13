"""Verification tests for the soft-LIFO accessibility packing.

Replaces the old strict-zone tests (pack_strict_sequence_zones is gone).
Covers:
  1. Bin._isAccessibleAt predicate - the core soft-LIFO rule.
  2. pack_soft_lifo end-to-end - no overlaps, all boxes fit.
  3. Regression - plain packer.pack() (seq=None path) still works.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from py3dbp import Packer, Bin, Item
from py3dbp.constants import RotationType


def _f(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def _box(it):
    d = it.getDimension()
    p = it.position
    return (_f(p[0]), _f(p[0]) + _f(d[0]),
            _f(p[1]), _f(p[1]) + _f(d[1]),
            _f(p[2]), _f(p[2]) + _f(d[2]))


def _overlaps(a, b):
    eps = 1e-9
    return (a[0] < b[1] - eps and b[0] < a[1] - eps and
            a[2] < b[3] - eps and b[2] < a[3] - eps and
            a[4] < b[5] - eps and b[4] < a[5] - eps)


def _any_overlap(bin_obj):
    items = list(bin_obj.items)
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if _overlaps(_box(items[i]), _box(items[j])):
                return (items[i].name, items[j].name)
    return None


def pack_soft_lifo(packer, manifest):
    """Local copy of app.pack_soft_lifo (app.py imports streamlit)."""
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
    return bin_obj


def _build(manifest, W=240, H=240, D=600, wt=10000):
    p = Packer()
    p.addBin(Bin("Truck", (W, H, D), wt))
    c = 0
    for obj in manifest:
        for i in range(obj["quantity"]):
            p.addItem(Item(
                partno="IT-{}".format(c),
                name='{} #{}'.format(obj["name"], i + 1),
                typeof="cube",
                WHD=(obj["w"], obj["h"], obj["d"]),
                weight=obj["weight"],
                level=1,
                loadbear=obj.get("max_load", 100),
                updown=obj.get("updown", True),
                color="#fff",
            ))
            c += 1
    return p


# ---------------------------------------------------------------------------
# Test 1: Bin._isAccessibleAt predicate (the core soft-LIFO rule)
# ---------------------------------------------------------------------------
print("=== Test 1: Bin._isAccessibleAt predicate ===")
b = Bin('t', (100, 100, 100), 1000)


def place(name, x, y, z, w, h, d, seq):
    it = Item(name, name, 'cube', (w, h, d), 1, 1, 100, True, '#fff')
    it.position = [x, y, z]
    it.rotation_type = 0
    it.sequence = seq
    b.items.append(it)
    return it


# Side-by-side (no x-overlap): higher-seq in front does NOT block
b.items.clear()
place('J', 50, 0, 60, 50, 50, 40, seq=3)
assert b._isAccessibleAt(0, 0, 0, 50, 50, 50, seq=1) is True
print("  S1 side-by-side -> accessible: PASS")

# Stacked (no y-overlap): higher-seq on top does NOT block
b.items.clear()
place('J', 0, 50, 0, 50, 50, 50, seq=3)
assert b._isAccessibleAt(0, 0, 0, 50, 50, 50, seq=1) is True
print("  S2 stacked -> accessible: PASS")

# Same lane + shelf, higher-seq fully in front -> BLOCKED
b.items.clear()
place('J', 0, 0, 60, 50, 50, 40, seq=3)
assert b._isAccessibleAt(0, 0, 0, 50, 50, 50, seq=1) is False
print("  S3 same lane+shelf, higher-seq in front -> blocked: PASS")

# Same lane + shelf, higher-seq BEHIND lower-seq -> accessible (correct LIFO)
b.items.clear()
place('J', 0, 0, 0, 50, 50, 40, seq=3)
assert b._isAccessibleAt(0, 0, 50, 50, 50, 50, seq=1) is True
print("  S4 higher-seq behind -> accessible: PASS")

# seq=None -> always accessible
b.items.clear()
place('J', 0, 0, 60, 50, 50, 40, seq=3)
assert b._isAccessibleAt(0, 0, 0, 50, 50, 50, seq=None) is True
print("  S5 seq=None -> accessible: PASS")

# Equal seq -> not a blocker
b.items.clear()
place('J', 0, 0, 60, 50, 50, 40, seq=1)
assert b._isAccessibleAt(0, 0, 0, 50, 50, 50, seq=1) is True
print("  S6 equal seq in front -> accessible: PASS")

# J only partially in front (z overlap but not fully) -> NOT blocked
b.items.clear()
place('J', 0, 0, 30, 50, 50, 40, seq=3)
assert b._isAccessibleAt(0, 0, 0, 50, 50, 50, seq=1) is True
print("  S7 partially in front -> accessible: PASS")
print("  Test 1 PASS")


# ---------------------------------------------------------------------------
# Test 2: pack_soft_lifo end-to-end (no overlaps, all fit)
# ---------------------------------------------------------------------------
print()
print("=== Test 2: pack_soft_lifo 3-sequence cube pack ===")
m1 = [
    {"name": "A", "w": 100, "h": 100, "d": 100, "weight": 10, "quantity": 3, "sequence": 1},
    {"name": "B", "w": 100, "h": 100, "d": 100, "weight": 10, "quantity": 3, "sequence": 2},
    {"name": "C", "w": 100, "h": 100, "d": 100, "weight": 10, "quantity": 3, "sequence": 3},
]
p = _build(m1)
b = pack_soft_lifo(p, m1)
print("  packed={} unfitted={}".format(len(b.items), len(getattr(b, 'unfitted_items', []))))
ov = _any_overlap(b)
assert ov is None, "overlap {}".format(ov)
assert len(getattr(b, "unfitted_items", [])) == 0, "unfitted!"
print("  Test 2 PASS")


# ---------------------------------------------------------------------------
# Test 3: regression - plain packer.pack() still works (seq=None path)
# ---------------------------------------------------------------------------
print()
print("=== Test 3: regression - plain packer.pack() ===")
p = _build(m1)
p.pack(bigger_first=False, fix_point=True, check_stable=True,
       support_surface_ratio=0.75, number_of_decimals=3)
b = p.bins[0]
print("  packed={}".format(len(b.items)))
ov = _any_overlap(b)
assert ov is None, "overlap {}".format(ov)
print("  Test 3 PASS")


print()
print("ALL SEQUENCE-FIX TESTS PASSED")
