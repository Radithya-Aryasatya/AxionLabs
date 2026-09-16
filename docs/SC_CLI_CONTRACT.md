# SC.CLI Contract v1.0

> JSON in → JSON out. The Sardine-Can C# CLI (`SC.CLI.exe`) is invoked via
> `subprocess`. It reads a `JsonInstance` (or `JsonCalculation`) from a file
> or stdin and writes a `JsonSolution` to stdout.

## Location of the C# project & binary

```
AI_modelsIntegration/
  sardine-can/
    SC.CLI/SC.CLI.csproj        ← Console entry point (net8.0, self-contained, single-file)
    SC.CLI/Program.cs
    SC.CLI/Executor.cs
    SC.Core/                    ← Library
```

The CLI is invoked as:

```
SC.CLI.exe -i input.json -o output.json
```

or via stdin → stdout:

```
SC.CLI.exe < input.json > output.json
```

If the executable is not found (e.g. offline machine), the Python
`solver_sardine.baseline.solve_sardine` fallback is used instead.

---

## C# coordinate system

```
x (Length)    = left-right  →  AxionLabs width  (truck_w, placement.x, placement.w)
y (Width)     = front-back  →  AxionLabs depth  (truck_d, placement.z, placement.d)
z (Height)    = floor-ceiling → AxionLabs height (truck_h, placement.y, placement.h)
```

The door is at **z = 0** in AxionLabs terms, which is **y = 0** in C# terms.

---

## Input JSON (`JsonInstance`)

```json
{
  "name": "AxionLabs-manifest-2024-09-16",
  "containers": [
    {
      "id": 1,
      "length": 2.4,      // x → truck_w
      "width": 6.0,       // y → truck_d
      "height": 2.4,      // z → truck_h
      "maxWeight": 4000
    }
  ],
  "pieces": [
    {
      "id": 0,
      "weight": 15.0,
      "flags": [
        {"flagId": 1, "flagValue": 1}   // (1,1) = ThisSideUp = keep height vertical
      ],
      "allowedOrientations": [0, 1, 2, 3],  // keep height vertical (z-axis stays H)
      "forbiddenOrientations": [],
      "cubes": [
        {
          "x": 0, "y": 0, "z": 0,
          "length": 0.08,  // x → w (meters)
          "width":  0.08,  // y → d (meters)
          "height": 0.08  // z → h (meters)
        }
      ],
      "data": {
        "name": "Generic Box",        // user data, preserved in output
        "sequence": 1,
        "max_load": 50.0,
        "quantity_idx": "0#1"
      }
    }
  ],
  "rules": {
    "flagRules": []
  }
}
```

### Flag / orientation conventions

**Flags** use the `HandlingInstructions` enum:
| flagId | flagValue | Meaning                              |
|--------|-----------|--------------------------------------|
| 1      | 1         | `ThisSideUp` — keep height vertical  |
| 1      | 2         | `NotStackable` — no weight above     |
| 1      | 3         | `Fragile` — not stackable + upright  |

**Orientations** (0–23, 24 total):
| IDs         | Meaning                                        |
|-------------|-------------------------------------------------|
| 0–3         | `ORIENTATIONS_THIS_SIDE_UP` — height stays vertical (z=up). These are the only valid orientations for `updown=False` items. |
| 0,1,4,5,16,17 | `ORIENTATIONS_PARALLELEPIPED_SUBSET` — 6 unique cuboid poses |

When AxionLabs `updown=False` (all items): set `allowedOrientations = [0, 1, 2, 3]`.

---

## Output JSON (`JsonSolution`)

```json
{
  "containers": [
    {
      "id": 1,
      "length": 2.4,
      "width": 6.0,
      "height": 2.4,
      "assignments": [
        {
          "piece": 0,
          "position": {
            "x": 0.0, "y": 3.0, "z": 0.0,
            "a": 0, "b": 0, "c": 0
          },
          "cubes": [
            {
              "x": 0, "y": 0, "z": 0,
              "length": 0.08,
              "width":  0.08,
              "height": 0.08
            }
          ],
          "data": { /* echoes the piece's input data */ }
        }
      ]
    }
  ],
  "offload": [
    {
      "piece": 5,
      "cubes": [...]
    }
  ]
}
```

### Output → AxionLabs Placement mapping

| C# field              | AxionLabs `Placement` field |
|------------------------|-----------------------------|
| `position.x`           | `.x` (left-right, meters)   |
| `position.z`           | `.y` (vertical, meters)     |
| `position.y`           | `.z` (front-back, meters)   |
| `cube.length`          | `.w` (width, meters)        |
| `cube.height`          | `.h` (height, meters)       |
| `cube.width`           | `.d` (depth, meters)        |
| `piece` id (lookup)    | `.name`, `.partno`, `.weight`, `.max_load`, `.color` |

### Rotation type mapping (C# orientation 0–23 → py3dbp 0–5)

For `allowedOrientations = [0,1,2,3]` (spin-only), the two unique poses are:

| C# orientation | Resulting cube dims        | py3dbp rotation_type |
|----------------|-----------------------------|----------------------|
| 0, 2           | `(L=W, W=D, H=H)` → `(w,d,h)` | `RT_WHD` (0)        |
| 1, 3           | `(W=D, L=W, H=H)` → `(d,w,h)` | `RT_DHW` (3)        |

> C# orientations 2 and 3 are the 180° flips of 0 and 1 — for cuboids with
> no internal asymmetry they produce identical dimension sets, so the
> bridge deduces `rotation_type` by comparing output `cube.length` to the
> original piece's `w`.
