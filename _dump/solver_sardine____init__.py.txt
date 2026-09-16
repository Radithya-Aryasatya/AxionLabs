"""
solver_sardine
==============
Python-native re-implementation of the SardineCan *Extreme Point Insertion*
heuristic (see ``sardine-can/SC.Core/Heuristics/PrimalHeuristic/
ExtremePointInsertion.cs``), adapted so it consumes the **same Excel /
sidebar manifest** and produces the **same output shape** as the classic
py3dbp engine in ``app.py``.

Key behaviours ported from the C# engine:

* **Extreme Points** — the container maintains a set of empty-space
  *extreme points* (corner vertices of already-placed items + container
  walls).  Every feasible item is tried at each extreme point instead of
  the py3dbp brute-force pivot sweep.
* **Best-fit merit** — for each (item, EP, rotation) the candidate whose
  *minimum residual slack* across all three axes is largest is chosen
  (the "best-fit" / MEDXYZ spirit).
* **Support / stability** — identical 0.75 surface-ratio rule used
  elsewhere in the codebase; the item's bottom footprint must be ≥ 75 %
  supported (or on the floor with no floating).
* **Orientation policy** — honours the *already-chosen* pose from
  ``orientation_editor`` (stored as ``w/h/d`` in meters).  ``updown``
  semantics map to rotation-type filtering: a non-tip-able item may only
  spin on the floor (``RT_WHD`` / ``RT_DHW``), never tip onto another
  face — exactly like ``RotationType.Notupdown`` in the classic engine.
* **Sequence / LIFO** — when ``prioritize_sequence`` is on, items are
  sorted highest-sequence-first (deepest first) and the same
  soft-LIFO accessibility guard used by ``pack_soft_lifo`` in
  ``app.py`` is enforced at placement.

The solver is structured so the **baseline** (``solver_sardine.baseline``
``solve_sardine``) always produces a valid layout equivalent to the
classic engine's, while the optional **improver**
(``solver_sardine.improver``) is free to try alternative strategies and
only replaces the baseline result when it is *strictly better* on the
same composite score.
"""
from .baseline import solve_sardine
from .improver import solve_with_improvement, solve

__all__ = ["solve", "solve_sardine", "solve_with_improvement"]
