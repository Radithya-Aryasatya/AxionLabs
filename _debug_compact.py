"""Debug the _compactBin overlap check failure."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from py3dbp import Packer, Bin, Item
import numpy as np


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


packer = Packer()
packer.addBin(Bin('Truck', (240, 240, 600), 4000))
bin_obj = packer.bins[0]
bin_obj.formatNumbers(3)

h = Item('H', 'H-Support #1', 'cube', (100, 50, 100), 10, 1, 100, False, '#ff0000')
h.formatNumbers(3)
h.position = [0, 0, 50]
h.rotation_type = 0
bin_obj.items.append(h)

g = Item('G', 'Blocker #1', 'cube', (100, 50, 150), 10, 1, 100, False, '#0000ff')
g.formatNumbers(3)
g.position = [0, 50, 50]
g.rotation_type = 0
bin_obj.items.append(g)

b = Item('B', 'Base #1', 'cube', (100, 50, 100), 10, 1, 100, False, '#00ff00')
b.formatNumbers(3)
b.position = [0, 0, 200]
b.rotation_type = 0
bin_obj.items.append(b)

f = Item('F', 'Top #1', 'cube', (100, 50, 100), 10, 1, 100, False, '#ffff00')
f.formatNumbers(3)
f.position = [0, 50, 200]
f.rotation_type = 0
bin_obj.items.append(f)

bin_obj._seq_floor = {'H': 50.0, 'G': 50.0, 'B': 200.0, 'F': 200.0}

print("Boxes:")
for it in bin_obj.items:
    print(f"  {it.name}: {_box(it)}")

print("\nOverlaps at initial positions:")
for i, a in enumerate(bin_obj.items):
    for j, b2 in enumerate(bin_obj.items):
        if i >= j:
            continue
        if _overlaps(_box(a), _box(b2)):
            print(f"  OVERLAP: {a.name} vs {b2.name}")

# Simulate the slide to z=150 and check
print("\nSimulate B+F at z=150:")
b.position = [0, 0, 150]
f.position = [0, 50, 150]
for it in bin_obj.items:
    print(f"  {it.name}: {_box(it)}")
for i, a in enumerate(bin_obj.items):
    for j, b2 in enumerate(bin_obj.items):
        if i >= j:
            continue
        if _overlaps(_box(a), _box(b2)):
            print(f"  OVERLAP: {a.name} vs {b2.name}")

# Now check what _rests_on says
print("\n_rests_on checks:")
def _rests_on(a, b):
    try:
        ad = a.getDimension(); bd = b.getDimension()
        ax0 = _f(a.position[0]); ay0 = _f(a.position[1]); az0 = _f(a.position[2])
        aw = _f(ad[0]); ah = _f(ad[1]); ad_ = _f(ad[2])
        bx0 = _f(b.position[0]); by0 = _f(b.position[1]); bz0 = _f(b.position[2])
        bw = _f(bd[0]); bh = _f(bd[1]); bd_ = _f(bd[2])
    except Exception:
        return False
    if abs(ay0 - (by0 + bh)) > 1e-6:
        return False
    ox = min(ax0 + aw, bx0 + bw) - max(ax0, bx0)
    oz = min(az0 + ad_, bz0 + bd_) - max(az0, bz0)
    return ox > 1e-6 and oz > 1e-6

for a in bin_obj.items:
    for b2 in bin_obj.items:
        if a is b2:
            continue
        if _rests_on(a, b2):
            print(f"  {a.name} rests on {b2.name}")

# Check _supported for F at z=150
print("\ncheckStable for F at z=150:")
print("  ", packer.checkStable(bin_obj, f, True, 0.75))
print("checkStable for B at z=150:")
print("  ", packer.checkStable(bin_obj, b, True, 0.75))