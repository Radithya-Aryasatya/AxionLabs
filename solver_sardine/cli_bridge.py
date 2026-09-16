"""
solver_sardine.cli_bridge
=========================
Bridge to the native Sardine-Can C# packing engine (SC.CLI.exe).

Architecture (see docs/MANIFEST_CONTRACT.md / docs/SC_CLI_CONTRACT.md):

* app.py owns Excel reading and the in-memory manifest. It calls
  solve_via_cli() with a canonical manifest (meters) - the C# engine
  NEVER touches Excel.
* This module converts the canonical manifest to the exact JSON shape that
  SC.CLI expects (JsonInstance / JsonCalculation), shells out to the
  compiled CLI via subprocess, and turns the JsonSolution reply back into a
  canonical result dict (then solver_common.interface.to_solution).
* If the CLI binary is missing or the run times out, _fallback()
  transparently delegates to the pure-Python solver_sardine.baseline so
  the UI never sees a crash - the Sardine-Can feature stays usable offline.

Coordinate mapping (meters in / meters out - NO cm anywhere here):

    AxionLabs (meters)   -->   C# SC.CLI (meters)
    -------------------      ----------------------
    width  (truck_w, p.w) --> length
    height (truck_h, p.h) --> height   (z, vertical axis)
    depth  (truck_d, p.d) --> width
    p.x                   --> x
    p.y (vertical)        --> z
    p.z (front-back)      --> y
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

# Make solver_common importable whether used as a package or standalone.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)            # AxionLabs/
if _PROJECT_ROOT not in sys.path and os.path.isdir(_PROJECT_ROOT):
    sys.path.insert(0, _PROJECT_ROOT)

# The C# project tree lives outside the AxionLabs workspace.
_CSHARP_ROOT = os.path.normpath(
    os.path.join(_PROJECT_ROOT, os.pardir, "AI_modelsIntegration", "sardine-can")
)

# Candidate locations for the compiled SC.CLI, in priority order.
_CLI_CANDIDATES = [
    os.path.join(_CSHARP_ROOT, "SC.CLI", "bin", "SC.CLI"),
    os.path.join(_CSHARP_ROOT, "SC.CLI", "bin", "Release", "net8.0", "SC.CLI"),
    os.path.join(_CSHARP_ROOT, "SC.CLI", "SC.CLI.csproj"),
]

# Default wall-clock ceiling for one CLI invocation, in seconds.
DEFAULT_TIMEOUT = 30.0

# py3dbp rotation-type constants for the (C# orientation 0-3 -> py3dbp 0/3) map.
_PY3DBP_RT_WHD = 0  # (w, h, d)
_PY3DBP_RT_DHW = 3  # (d, h, w)

# HandlingInstructions enum values (SC.Core.ObjectModel.Additionals).
FLAG_THIS_SIDE_UP = 1
FLAG_NOT_STACKABLE = 2
FLAG_FRAGILE = 3

#: ORIENTATIONS_THIS_SIDE_UP - height axis stays vertical. The only
#: orientation family compatible with AxionLabs updown=False policy
#: (spin on the floor, never tip).
ORIENTATIONS_THIS_SIDE_UP = [0, 1, 2, 3]


# ------------------------------------------------------------------
#  Manifest -> SC.CLI JSON
# ------------------------------------------------------------------

def to_sc_manifest(canonical: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a canonical manifest dict into the SC.CLI JsonInstance shape.

    The canonical manifest is the output of
    solver_common.interface.to_canonical() - items already carry their
    orientation (w/h/d in meters) chosen by orientation_editor.
    """
    truck = canonical["truck"]
    container = {
        "id": 1,
        "length": round(float(truck["width"]), 6),   # x <- m
        "width": round(float(truck["depth"]), 6),    # y <- m
        "height": round(float(truck["height"]), 6),  # z <- m
        "maxWeight": float(truck["max_weight"]),
    }

    pieces: List[Dict[str, Any]] = []
    counter = 0
    for item in canonical["items"]:
        qty = int(item.get("quantity", 1))
        base_name = str(item.get("base_id") or item["name"])
        for i in range(qty):
            qidx = f"{base_name}#{i + 1}"
            data_name = str(item["name"])
            # Fragile -> NotStackable + ThisSideUp (flagId 1, value 3).
            if bool(item.get("fragile")):
                flags = [{"flagId": FLAG_THIS_SIDE_UP,
                          "flagValue": FLAG_FRAGILE}]
            else:
                flags = []
            ml = item.get("max_load")
            data = {
                "name": data_name,
                "sequence": int(item["sequence"]),
                "max_load": float(ml) if ml is not None else None,
                "quantity_idx": qidx,
                "partno": f"{data_name} #{i + 1}",
            }
            pieces.append({
                "id": counter,
                "weight": float(item["weight"]),
                "flags": flags,
                # updown=False => spin-only orientations (height stays vertical)
                "allowedOrientations": list(ORIENTATIONS_THIS_SIDE_UP),
                "forbiddenOrientations": [],
                "cubes": [{
                    "x": 0.0, "y": 0.0, "z": 0.0,
                    "length": round(float(item["w"]), 6),    # x <- w
                    "width": round(float(item["d"]), 6),     # y <- d
                    "height": round(float(item["h"]), 6),    # z <- h
                }],
                "data": data,
            })
            counter += 1

    return {
        "name": canonical.get("name", "AxionLabs-manifest"),
        "containers": [container],
        "pieces": pieces,
        "rules": {"flagRules": []},
    }


def _sc_config(budget_seconds: float) -> Dict[str, Any]:
    """Minimal Configuration block for SC.CLI.

    timeLimit is a System.TimeSpan; we emit it as seconds and let the
    C# side wrap it with TimeSpan.FromSeconds. The method defaults to
    ExtremePointInsertion, the engine this project targets.
    """
    return {
        "name": "AxionLabs-EPI",
        "timeLimit": max(1.0, float(budget_seconds)) if budget_seconds else 30.0,
        "type": "EXTREMEPOINTINSERTION",
        "handleGravity": True,
        "handleCompatibility": True,
        "handleStackability": True,
        "handleRotatability": True,
    }


def wrap_in_calculation(instance: Dict[str, Any],
                        config: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap an instance + config into the JsonCalculation envelope that
    SC.CLI accepts on stdin / -i.
        """
    return {"configuration": config, "instance": instance}


# ------------------------------------------------------------------
#  SC.CLI JSON -> Solution
# ------------------------------------------------------------------

def _csha_orientation_to_py3dbp(length: float, width: float, height: float,
                                item_w: float) -> int:
    """Map a C# spin-only orientation (allowedOrientations=[0,1,2,3],
    height stays vertical) to the closest py3dbp rotation_type.

    C# orientation 0/2 -> (len=W, wid=D, hei=H) -> (w,d,h) -> RT_WHD (0)
    C# orientation 1/3 -> (wid=D, len=W, hei=H) -> (d,w,h) -> RT_DHW (3)
    """
    if abs(length - item_w) <= 1e-6:
        return _PY3DBP_RT_WHD
    return _PY3DBP_RT_DHW


def parse_sc_solution(raw: Dict[str, Any],
                      canonical: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a JsonSolution dict into the canonical result shape::

        {"truck": {...}, "packed": [...], "unfitted": [...]}

    handed to solver_common.interface.to_solution(). All numbers in meters.
    """
    truck = canonical["truck"]
    result: Dict[str, Any] = {
        "truck": {
            "name": truck.get("name", "Truck"),
            "width": float(truck["width"]),
            "height": float(truck["height"]),
            "depth": float(truck["depth"]),
            "max_weight": float(truck["max_weight"]),
        },
        "packed": [],
        "unfitted": [],
    }

    # Rebuild (quantity_idx) -> original item descriptor lookup.
    item_lookup: Dict[str, Dict[str, Any]] = {}
    for item in canonical["items"]:
        qty = int(item.get("quantity", 1))
        for i in range(qty):
            qidx = f"{item.get('base_id') or item['name']}#{i + 1}"
            item_lookup[qidx] = item

    containers = raw.get("containers") or []
    offload = raw.get("offload") or []
    for cont in containers:
        for assign in cont.get("assignments") or []:
            cube = (assign.get("cubes") or [{}])[0]
            pos = assign.get("position") or {}
            data = assign.get("data") or {}
            qidx = data.get("quantity_idx", "")
            meta = item_lookup.get(qidx, {})
            length = float(cube.get("length", 0.0))   # -> AxionLabs width
            width = float(cube.get("width", 0.0))     # -> AxionLabs depth
            height = float(cube.get("height", 0.0))   # -> AxionLabs height
            item_w = float(meta.get("w", 0.0))
            rt = _csha_orientation_to_py3dbp(length, width, height, item_w)
            result["packed"].append({
                # C# (x,y,z) = AxionLabs (x, z, y)
                "name": data.get("partno") or meta.get("name", qidx),
                "partno": data.get("partno") or qidx,
                "x": float(pos.get("x", 0.0)),
                "y": float(pos.get("z", 0.0)),  # vertical
                "z": float(pos.get("y", 0.0)),  # front-back
                "w": length,                    # AxionLabs width
                "h": height,                    # AxionLabs height
                "d": width,                     # AxionLabs depth
                "weight": float(meta.get("weight", 0.0)),
                "rotation_type": rt,
                "max_load": (None if meta.get("max_load") is None
                             else float(meta["max_load"])),
                "color": meta.get("color", "#1f77b4"),
            })
    for off in offload:
        data = off.get("data") or {}
        qidx = data.get("quantity_idx", "")
        meta = item_lookup.get(qidx, {})
        result["unfitted"].append({
            "name": data.get("partno") or meta.get("name", qidx),
            "partno": data.get("partno") or qidx,
                        "x": 0.0, "y": 0.0, "z": 0.0,
            "w": float(meta.get("w", 0.0)),
            "h": float(meta.get("h", 0.0)),
            "d": float(meta.get("d", 0.0)),
            "weight": float(meta.get("weight", 0.0)),
            "rotation_type": _PY3DBP_RT_WHD,
            "max_load": (None if meta.get("max_load") is None
                         else float(meta["max_load"])),
            "color": meta.get("color", "#1f77b4"),
        })
    return result



# ------------------------------------------------------------------
#  CLI discovery + invocation
# ------------------------------------------------------------------

def find_cli() -> Optional[str]:
    """Return a runnable CLI path/command, or None if unavailable.

    Lookup order: SC_CLI env override, shipped binary, then dotnet run.
    """
    for env_var in ("SC_CLI", "SOLARINE_CLI"):
        val = os.environ.get(env_var)
        if val:
            if shutil.which(val):
                return val
            if os.path.isfile(val):
                return val
    for cand in _CLI_CANDIDATES:
        if os.path.isfile(cand):
            if cand.endswith(".csproj"):
                if shutil.which("dotnet"):
                    return "dotnet run --project " + os.path.dirname(cand)
                continue
            if shutil.which(cand) or os.access(cand, os.X_OK):
                return cand
    return None


def _cli_argv(cli_path: str) -> List[str]:
    """Split a find_cli() result into an argv list."""
    return cli_path.split()


def _extract_trailing_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort extraction of the trailing JSON object from CLI stdout."""
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    continue
    return None


def _run_cli_subprocess(argv: List[str], input_json: str,
                        timeout: float) -> Tuple[Optional[Dict[str, Any]], str]:
    """Shell out to the C# CLI. Returns (parsed_solution|None, message)."""
    try:
        proc = subprocess.run(
            argv, input=input_json, capture_output=True,
            text=True, timeout=timeout, check=False,
        )
    except (FileNotFoundError, OSError) as exc:
        return None, f"CLI spawn failed: {exc}"
    except subprocess.TimeoutExpired:
        return None, "CLI timed out"
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        return None, f"CLI error ({proc.returncode}): {msg}"
    out = (proc.stdout or "").strip()
    if not out:
        return None, "CLI produced no output"
    try:
        return json.loads(out), ""
    except json.JSONDecodeError:
        return _extract_trailing_json(out), "JSON parse error"


# ------------------------------------------------------------------
#  Public entry point
# ------------------------------------------------------------------

def solve_via_cli(canonical_manifest: Dict[str, Any],
                  budget_seconds: float = DEFAULT_TIMEOUT,
                  timeout: float = DEFAULT_TIMEOUT) -> Tuple[bool, Any]:
    """Run the canonical manifest through the native C# SC.CLI engine.

    Returns (used_native, solution) where:
      * used_native - True if the C# engine produced a usable result.
      * solution - a solver_common.schemas.Solution. On any CLI failure the
        pure-Python solver_sardine.baseline result is returned instead, so the
        caller always receives a valid layout (never an exception).

    The C# engine is never given Excel files - only this JSON payload.
    """
    from solver_common.interface import to_solution
    from solver_sardine import baseline

    truck = canonical_manifest.get("truck", {})
    inst = to_sc_manifest(canonical_manifest)
    calc = wrap_in_calculation(inst, _sc_config(budget_seconds))
    payload = json.dumps(calc)

    cli_path = find_cli()
    if cli_path is None:
        return _fallback(canonical_manifest, baseline, "SC.CLI not found")

    argv = _cli_argv(cli_path)
    parsed, err = _run_cli_subprocess(argv, payload, timeout=timeout)
    if parsed is None:
        return _fallback(canonical_manifest, baseline, err or "CLI failed")

    try:
        canonical_result = parse_sc_solution(parsed, canonical_manifest)
        sol = to_solution(
            canonical_result,
            engine="sardine-can",
            strategy="epi-csharp",
        )
        sol.score = _quick_volume_score(sol, truck)
        sol.extra["budget_s"] = float(budget_seconds)
        sol.extra["cli"] = True
        if err:
            sol.extra["cli_warning"] = err
        return True, sol
    except Exception as exc:                       # parsing error -> fallback
        return _fallback(canonical_manifest, baseline, f"parse: {exc}")


def _quick_volume_score(solution: Any, truck: Dict[str, Any]) -> float:
    """Lightweight volume-utilisation percentage for the bridge result."""
    try:
        tvol = (float(truck["width"]) * float(truck["height"])
                * float(truck["depth"]))
    except Exception:
        tvol = 1.0
    if tvol <= 0:
        tvol = 1.0
    packed_vol = sum(p.w * p.h * p.d for p in solution.packed)
    return max(0.0, min(1.0, packed_vol / tvol)) * 100.0


def _fallback(canonical_manifest: Dict[str, Any], baseline_module,
              reason: str = "") -> Tuple[bool, Any]:
    """Offline path: delegate to the pure-Python baseline engine.

    solve_sardine() consumes the *raw* app.py manifest dicts, so we prefer an
    injected ``_raw_manifest``; otherwise we re-derive a minimal raw manifest
    from the canonical items (the baseline only needs name/sequence/weight/
    w/h/d/quantity/max_load).
    """
    raw = canonical_manifest.get("_raw_manifest")
    if raw is None:
        raw = []
        for it in canonical_manifest.get("items", []):
            ml = it.get("max_load")
            raw.append({
                "name": str(it["name"]),
                "w": float(it["w"]),
                "h": float(it["h"]),
                "d": float(it["d"]),
                "weight": float(it["weight"]),
                "quantity": int(it.get("quantity", 1)),
                "sequence": int(it["sequence"]),
                "max_load": (float("inf") if ml is None else float(ml)),
                "fragile": bool(it.get("fragile")),
                "color": it.get("color", "#1f77b4"),
            })
    truck = canonical_manifest["truck"]
    sol = baseline_module.solve_sardine(
        raw,
        float(truck["width"]),
        float(truck["height"]),
        float(truck["depth"]),
        float(truck["max_weight"]),
    )
    sol.engine = "sardine-baseline"
    sol.strategy = "epi-baseline"
    sol.extra["fallback"] = True
    if reason:
        sol.extra["fallback_reason"] = reason
    return False, sol


__all__ = [
    "to_sc_manifest", "parse_sc_solution", "find_cli",
    "wrap_in_calculation", "solve_via_cli", "ORIENTATIONS_THIS_SIDE_UP",
    "FLAG_THIS_SIDE_UP", "FLAG_NOT_STACKABLE", "FLAG_FRAGILE",
    "DEFAULT_TIMEOUT",
]
