"""
Shared data schemas for the pluggable bin-packing engines.

Everything here is unit-agnostic at the schema level (the solver always
receives and returns **meters** for lengths — see ``app.py``'s manifest
which already stores w/h/d in meters).  Conversion to/from centimetres
happens only at the py3dbp boundary inside the classic adapter.
"""
from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class CargoItem:
    """One *type* of cargo (before quantity expansion).

    ``width / height / depth`` are in **meters** — they already reflect
    the user's chosen orientation from ``orientation_editor`` (which writes
    the user's pose into the manifest as ``w/h/d`` in metres).

    ``max_load``:
        * Fragile items → the item's own weight (cannot be stacked on).
        * Non-fragile   → ``float('inf')`` (py3dbp sentinel meaning
          "no restriction"), matching ``app.py``'s import branch.

    ``sequence`` is the unloading sequence (1 = off-loaded first).
    """
    name: str
    width: float   # meters
    height: float
    depth: float
    weight: float  # kg
    max_load: float
    sequence: int
    quantity: int = 1
    # Instance id used to disambiguate individual units (e.g. "Box #3").
    base_id: Optional[str] = None

    def volume(self) -> float:
        return self.width * self.height * self.depth


@dataclass
class Truck:
    """Container / vehicle dimensions in **meters**."""
    name: str
    width: float
    height: float
    depth: float
    max_weight: float  # kg

    def volume(self) -> float:
        return self.width * self.height * self.depth


@dataclass
class Placement:
    """A single placed cargo unit inside the truck (meters)."""
    name: str
    partno: str
    x: float
    y: float
    z: float
    w: float  # width  (m)
    h: float  # height (m)  — vertical axis
    d: float  # depth  (m)
    weight: float
    rotation_type: int       # 0-5, same enum as py3dbp RotationType
    max_load: float
    color: str = "#1f77b4"

    def footprint_area(self) -> float:
        return self.w * self.d

    def corners_xz(self) -> List[Tuple[float, float]]:
        """Bottom-face corners in the X-Z plane (truck width × truck depth)."""
        return [(self.x, self.z),
                (self.x + self.w, self.z),
                (self.x, self.z + self.d),
                (self.x + self.w, self.z + self.d)]


@dataclass
class Solution:
    """Result of a packing run — consumed by ``app.py``'s metric + viewer layer.

    ``packed`` / ``unfitted`` are lists of :class:`Placement`.  The caller
    (``app.py``) converts each ``Placement`` into a ``PackedItem`` for the
    existing 3-D viewer, utilisation, load-distribution, floating-item and
    blocking-score calculations — those helpers operate on ``PackedItem``
    and are therefore shared between every engine without any change.
    """
    truck: Truck
    packed: List[Placement] = field(default_factory=list)
    unfitted: List[Placement] = field(default_factory=list)
    engine: str = "unknown"
    score: float = 0.0
    # Human-readable explanation of how the score was achieved
    # (e.g. "baseline" / "swap-improvement w=0.3").
    strategy: str = "baseline"
    # Free-form metadata (timings, extra diagnostics, AI win/loss info …)
    extra: dict = field(default_factory=dict)
