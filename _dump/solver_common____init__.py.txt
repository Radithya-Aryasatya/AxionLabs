"""
solver_common
==============
Shared data schemas and interfaces for the pluggable bin-packing engines.

Both the Classic (py3dbp) engine and the Sardine-Can AI engine implement the
same ``solve()`` contract defined here, so ``app.py`` can swap engines
without changing the UI, metrics, 3-D viewer, or fleet-registration path.
"""
from .schemas import CargoItem, Truck, Placement, Solution
from .interface import solve, _manifest_to_items, expand_items, score_solution

__all__ = [
    "CargoItem", "Truck", "Placement", "Solution",
    "solve", "_manifest_to_items", "expand_items", "score_solution",
]
