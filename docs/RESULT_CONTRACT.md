# RESULT CONTRACT v1.0

> **Single output schema.** Both the Classic (py3dbp) engine and the
> Sardine-Can AI engine return a `solver_common.schemas.Solution` whose
> `packed` and `unfitted` lists are consumed identically by `app.py`'s
> metrics, 3-D viewer, and fleet-registration code. The UI never needs to
> know which engine produced the result.

---

## 1. Solution dataclass (`solver_common.schemas.Solution`)

```python
@dataclass
class Solution:
    truck:     Truck
    packed:    List[Placement]       # successfully placed boxes (meters)
    unfitted:  List[Placement]       # boxes that could not be placed
    engine:    str                   # "classic" | "sardine" | "sardine-cli"
    score:     float                 # composite score (0–100)
    strategy:  str                   # "baseline" | "epi-baseline" | strategy name
    extra:     dict                  # diagnostics, timings, weights, …
```

### `extra` keys used by `app.py`

| Key                  | Type    | Description                                       |
|----------------------|---------|--------------------------------------------------|
| `gravity`            | `list`  | py3dbp gravity centre (classic only)             |
| `prioritize_sequence`| `bool`  | Whether LIFO was enforced                         |
| `method`             | `str`   | Algorithm name (e.g. `"ExtremePointInsertion"`)  |
| `utilization`        | `float` | 0–100 % volume utilization                        |
| `safety_rate`        | `float` | 0–100 % load-distribution safety                 |
| `offloading_score`   | `float` | 0–100 soft-LIFO accessibility score              |
| `floating_count`     | `int`   | Count of items with < 75 % support                |
| `baseline_score`     | `float` | Baseline score the improver started from          |
| `improved`           | `bool`  | Whether any strategy beat the baseline            |
| `elapsed_s`          | `float` | Wall-clock seconds spent                         |

---

## 2. Placement dataclass (`solver_common.schemas.Placement`)

```python
@dataclass
class Placement:
    name:           str
    partno:         str
    x:              float    # meters — left-right
    y:              float    # meters — vertical (floor = 0)
    z:              float    # meters — front-back (door = 0)
    w:              float    # meters — width  (left-right)
    h:              float    # meters — height (vertical)
    d:              float    # meters — depth  (front-back)
    weight:         float    # kg
    rotation_type:  int      # 0–5 (py3dbp RotationType enum)
    max_load:       float    # kg (inf = no restriction)
    color:          str = "#1f77b4"
```

### Coordinate mapping (C# SC.CLI → AxionLabs)

The C# engine uses a right-handed system where **x = left-right**,
**y = front-back**, **z = bottom-top**.  The Python viewer uses
**x = left-right**, **y = bottom-top**, **z = front-back**.

| C# field              | AxionLabs field     |
|------------------------|---------------------|
| `position.x`           | `Placement.x`       |
| `position.z` (height)  | `Placement.y`       |
| `position.y` (depth)   | `Placement.z`       |
| `cube.length`          | `Placement.w`       |
| `cube.height`          | `Placement.h`       |
| `cube.width`           | `Placement.d`       |

### Py3dbp rotation_type enum (must be preserved for the viewer)

| Value | Name     | Dimensions (w, h, d)  | Meaning                          |
|-------|----------|------------------------|----------------------------------|
| 0     | `RT_WHD` | `(w, h, d)`            | Base pose (user's chosen stance) |
| 1     | `RT_HWD` | `(h, w, d)`            | Tipped — only for `updown=True`  |
| 2     | `RT_HDW` | `(h, d, w)`            | Tipped — only for `updown=True`  |
| 3     | `RT_DHW` | `(d, h, w)`            | Floor spin (mirror of 0)         |
| 4     | `RT_DWH` | `(d, w, h)`            | Tipped — only for `updown=True`  |
| 5     | `RT_WDH` | `(w, d, h)`            | Tipped — only for `updown=True`  |

`updown=False` (all AxionLabs items) → only rotation types **0** and **3**
are valid (spin on floor, never tip).

---

## 3. Truck dataclass (`solver_common.schemas.Truck`)

```python
@dataclass
class Truck:
    name:       str        # always "Truck"
    width:      float      # meters (left-right) →  C# container.length
    height:     float      # meters (floor-ceiling) → C# container.height
    depth:      float      # meters (door-to-tail) →  C# container.width
    max_weight: float      # kg
```

---

## 4. Conversion to `PackedItem` (app.py level)

`app.py` converts each `Placement` into a `PackedItem` for the existing
viewer/metrics code:

```
PackedItem(name, x, y, z, w, h, d, weight, max_load)
             │   │ │ │ │ │ │ │
             └←───┴─┴─┴─┴─┴─┴─┴── from Placement fields (meters, kg)
```

The metrics layer then computes:

```
util    = calculate_utilization(packed, truck_vol)          # 0–100
safety  = load_distribution check vs max_load               (0–100)
offload = calculate_offloading_score(packed, manifest_lookup) (0–100)

overall = util * 0.4 + safety * 0.4 + offload * 0.2
```

---

## 5. `to_solution()` Pipeline

Defined in `solver_common/interface.py`:

```
Solution (from any engine)
    ├─ truck   →  Truck dataclass
    ├─ packed   →  Placement objects (meters)
    ├─ unfitted →  Placement objects (meters, x=y=z=0)
    ├─ engine   →  "classic" / "sardine" / "sardine-cli"
    ├─ score    →  composite 0–100
    ├─ strategy →  strategy label
    └─ extra    →  diagnostics dict
```

All positions and dimensions are in **metres**. The classic adapter
converts cm → m (`/100`) when extracting from py3dbp; the C# bridge
converts the C# coordinate system to the AxionLabs coordinate system.
