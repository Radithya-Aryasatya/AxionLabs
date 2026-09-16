# MANIFEST CONTRACT v1.0

> **Single source of truth for the canonical cargo manifest.**
> Every engine — Classic (py3dbp) and Sardine-Can AI — consumes **exactly**
> this dict shape from `st.session_state.manifest`. No engine reads Excel
> directly; `app.py` is the sole Excel reader.

---

## 1. Excel Input Shape (read by `app.py` only)

| Excel Column                  | Python type | Unit   | Notes                                         |
|-------------------------------|-------------|--------|-----------------------------------------------|
| `Item Description`            | `str`       | —      | Cargo name / part number                      |
| `Box Quantity`                | `int`       | count  | How many identical boxes                      |
| `Box Weight (kg)`             | `float`     | kg     | Per-box weight (all copies identical)         |
| `Length (cm)`                 | `float`     | cm     | Maps to **depth** `d` in the truck            |
| `Width (cm)`                  | `float`     | cm     | Maps to **width** `w` in the truck            |
| `Height (cm)`                 | `float`     | cm     | Maps to **height** `h` in the truck           |
| `Fragile`                     | `str`       | —      | `"yes"`/`"y"`/`"true"`/`"1"` → fragile       |
| `Unloading Sequence`          | `int`       | 1-based | `1` = unloaded first (placed near door)      |

### Manual-add path (sidebar widgets)

| Widget                       | Key in dict | Unit conversion | Notes                              |
|------------------------------|-------------|------------------|------------------------------------|
| Item Name                    | `name`      | —                | `str`                              |
| Item Width (cm)              | `w`         | `cm → m` (÷100)  | Left-right dimension               |
| Item Height (cm)             | `h`         | `cm → m` (÷100)  | Vertical dimension                 |
| Item Depth (cm)              | `d`         | `cm → m` (÷100)  | Front-back dimension               |
| Item Weight (kg)             | `weight`    | —                | `float`                            |
| Maximum Supported Load (kg)  | `max_load`  | —                | `float('inf')` if not fragile      |
| Quantity                     | `quantity`  | —                | `int`, ≥ 1                         |
| Unloading Sequence           | `sequence`  | —                | `int`, ≥ 1                         |

### Orientation Editor

When a user confirms an orientation via `orientation_editor.py`, the
returned dict has keys `w`, `h`, `d` (meters) reflecting the **user-chosen
pose**. The solver must respect this pose: `updown=False` means the item may
only **spin on the floor** (rotate around the vertical axis), never tip onto
another face.

---

## 2. Canonical Manifest Shape (in-memory)

`st.session_state.manifest` is a `list[dict]`. Each element:

```jsonc
{
  "name":           "Generic Box",        // str  — cargo description
  "w":              0.08,                 // float — meters (left-right)
  "h":              0.08,                 // float — meters (vertical)
  "d":              0.08,                 // float — meters (front-back)
  "weight":         15.0,                 // float — kg
  "quantity":       1,                    // int   — box count
  "max_load":       50.0,                 // float or Infinity — kg supported above
  "sequence":       1,                    // int   — 1 = unloaded first
    "orientation_index": 0,                 // int   — index into user's chosen pose
}
```

### Derived / computed by `app.py`

| Value             | Expression (meters)        | Source in manifest |
|-------------------|----------------------------|--------------------|
| `truck_w`         | sidebar number_input       | user               |
| `truck_h`         | sidebar number_input       | user               |
| `truck_d`         | sidebar number_input       | user               |
| `truck_weight`    | sidebar number_input       | user (kg)          |
| `loading_order`   | sorted by `(-sequence, max_load, -(w*h*d), -weight)` | manifest |

### Unit rules

* **All dimensions in the manifest are metres.**
* Centimetres → metres conversion (`÷100`) happens **only** inside
  `app.py`'s Excel-import branch and `orientation_editor.py`.
* The classic py3dbp adapter multiplies metres → centimetres (`*100`)
  internally; the Sardine-Can engines receive metres and pass centimetres
  only at their own internal boundary (if any).

---

## 3. `to_canonical()` Pipeline

Defined in `solver_common/interface.py`:

```
manifest (list[dict])  →  _manifest_to_items()  →  list[CargoItem]
                           │
                           ├─  CargoItem.name       = dict["name"]
                           ├─  CargoItem.width      = dict["w"]   (m)
                           ├─  CargoItem.height     = dict["h"]   (m)
                           ├─  CargoItem.depth      = dict["d"]   (m)
                           ├─  CargoItem.weight     = dict["weight"]     (kg)
                           ├─  CargoItem.max_load   = dict["max_load"]   (kg or inf)
                           ├─  CargoItem.sequence   = dict["sequence"]   (int)
                           ├─  CargoItem.quantity   = dict.get("quantity", 1)
                           └─  CargoItem.base_id    = str(idx)

expand_items()  →  one CargoItem per physical box (quantity expansion)
                   base_id becomes "idx#1", "idx#2", …
```

### CargoItem dataclass fields

| Field         | Type   | Unit | Notes                                           |
|---------------|--------|------|-------------------------------------------------|
| `name`        | `str`  | —    | Cargo name                                      |
| `width`       | `float`| m    |                                                 |
| `height`      | `float`| m    |                                                 |
| `depth`       | `float`| m    |                                                 |
| `weight`      | `float`| kg   |                                                 |
| `max_load`    | `float`| kg   | `inf` = no restriction                          |
| `sequence`    | `int`  | —    | 1 = unloaded first                              |
| `quantity`    | `int`  | —    | Pre-expansion quantity                          |
| `base_id`     | `str`  | —    | Disambiguator (e.g. `"2#3"` for 3rd copy of idx 2) |

---

## 4. Truck Meta

Truck dimensions and max-weight are **passed as separate parameters** to
every `solve()` call — they are **not** part of `st.session_state.manifest`.

| Parameter    | Unit | Meaning                        |
|--------------|------|--------------------------------|
| `truck_w`    | m    | Interior width  (left-right)   |
| `truck_h`    | m    | Interior height (floor-ceiling)|
| `truck_d`    | m    | Interior depth  (door-to-tail) |
| `truck_weight` | kg | Max payload                    |

The coordinate system (matches py3dbp and the 3-D viewer):

```
   x  ←→  width  (left-right)
   y  ←→  height (floor-ceiling)
   z  ←→  depth  (door → tail)
```

The door is at **z = 0**; the tail gate is at **z = truck_d**.  Sequence 1
boxes should end up near z = 0 (door side).
```
