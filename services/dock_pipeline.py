"""
services/dock_pipeline.py
=========================
Dock 1 fleet plumbing for the Executive dashboard.

Note: the worker's "Render" button triggers NO analysis and shows NO
notifications - Gemini scans are started exclusively from the
Executive dashboard.

- analyze_with_fallback: REAL Gemini spatial reasoning with a hard timeout,
  used by the Executive dashboard scan orchestrator and audit panel.
- ensure_dock1_monitor_fleet: keeps a neutral Dock-1 placeholder fleet so
  the Executive dashboard always has something to display.

Provenance contract (no false successes):
  - A successful REAL Gemini reply is labelled AnalysisSource.LIVE_GEMINI.
  - A failed/timed-out request is labelled AnalysisSource.GEMINI_FAILED and
    is passed through AS-IS (real error, attempted model, empty raw text).
    It is never replaced with simulated, cached or canned data.
  - Deterministic simulation happens ONLY when no API key/SDK is configured
    and is always labelled AnalysisSource.FALLBACK_SIMULATED.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Optional, Tuple

from state.fleet_state import Fleet
from state.dock_state import (
    upsert_dock_fleet, set_dock_stage, set_analysis_source,
    DockStage, AnalysisSource,
)
from services.gemini_service import (
    GeminiService, GeminiAnalysisResult,
    STATUS_SUCCESS, STATUS_FAILED, STATUS_SIMULATED,
)
from services.anomaly_engine import AnomalyEngine
from services import mock_fleet_factory

log = logging.getLogger("dock_pipeline")

# Timeout (seconds) for the real Gemini API call. Tunable via env.
# Generous enough to absorb the SDK's transient-error retry ladder
# (2+4+8+16s backoff) during Google-side "high demand" 503 spikes.
ANALYSIS_TIMEOUT_S = float(os.getenv("ANALYSIS_TIMEOUT_S", "120"))


def _failed_from_exception(svc: GeminiService, exc: Exception) -> GeminiAnalysisResult:
    """Wrap an unexpected pipeline error as an honest FAILED result."""
    return GeminiAnalysisResult(
        anomaly_type="OTHER", severity="NONE",
        analysis_paragraph="", status=STATUS_FAILED, model=svc.model,
        raw_response="", error=f"{type(exc).__name__}: {exc}",
    )


def analyze_with_fallback(
    fleet: Fleet,
    virtual_cctv_path: Optional[str] = None,
) -> Tuple[GeminiAnalysisResult, AnalysisSource]:
    """
    Run REAL Gemini spatial reasoning with a hard timeout.

    Returns (result, source) where the source reflects provenance honestly:
      result.status == SUCCESS   -> AnalysisSource.LIVE_GEMINI   (real reply)
      result.status == FAILED    -> AnalysisSource.GEMINI_FAILED (passed through
                                    as-is; never swapped for simulated data)
      result.status == SIMULATED -> AnalysisSource.FALLBACK_SIMULATED (only when
                                    no API key/SDK is configured at all)

    Optional ``virtual_cctv_path`` is the SECONDARY digital-twin rear-camera
    render (content-addressed PNG from services/virtual_camera.py). When a dock
    has no twin yet (Dock 1 before worker render) it is simply omitted and the
    scan falls back to CCTV-only analysis.
    """
    svc = GeminiService()
    engine = AnomalyEngine(gemini_service=svc)

    cctv = fleet.cctv_frame_path or mock_fleet_factory.ensure_dock_assets(
        fleet.dock_number)

    # Normalize the twin path: only pass it when the file actually exists.
    twin = virtual_cctv_path if (virtual_cctv_path and os.path.isfile(virtual_cctv_path)) else ""

    def _call():
        return svc.analyze_loading(
            cctv_frame_path=cctv,
            packing_plan=fleet.packing_layout,
            manifest=fleet.manifest,
            fleet_state=engine._fleet_to_state_dict(fleet),
            virtual_cctv_path=twin,
        )

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call)
            result = future.result(timeout=ANALYSIS_TIMEOUT_S)
    except TimeoutError:
        log.error(
            "Gemini analysis timed out after %.0fs (model=%s) — reporting "
            "GEMINI FAILED; NOT substituting simulated data.",
            ANALYSIS_TIMEOUT_S, svc.model,
        )
        result = GeminiAnalysisResult(
            anomaly_type="OTHER", severity="NONE",
            analysis_paragraph="", status=STATUS_FAILED, model=svc.model,
            raw_response="",
            error=(f"RequestTimeout: Gemini ({svc.model}) did not respond "
                   f"within {ANALYSIS_TIMEOUT_S:.0f}s"),
        )
        return result, AnalysisSource.GEMINI_FAILED
    except Exception as e:
        log.error("Gemini analysis pipeline error: %s: %s", type(e).__name__, e)
        return _failed_from_exception(svc, e), AnalysisSource.GEMINI_FAILED

    # Honest provenance mapping — simulated/failed data is never labelled live.
    if result.status == STATUS_SUCCESS:
        return result, AnalysisSource.LIVE_GEMINI
    if result.status == STATUS_FAILED:
        log.error(
            "Gemini request FAILED (model=%s): %s", result.model, result.error
        )
        return result, AnalysisSource.GEMINI_FAILED
    if result.status == STATUS_SIMULATED:
        return result, AnalysisSource.FALLBACK_SIMULATED
    # Unknown legacy status — surface it as simulated, never as live.
    return result, AnalysisSource.FALLBACK_SIMULATED


def ensure_dock1_monitor_fleet():
    """Ensure Dock 1 always has a fleet for the Executive dashboard to display.

    Idempotent:
      - If a live Dock-1 fleet already exists, it is left untouched — only the
        CCTV pairing is refreshed.
      - If no live Dock-1 fleet exists, a neutral monitor placeholder is
        created (empty packing layout, CCTV assets pinned, stage
        ``MONITORED``, analysis source ``NONE``) so the dashboard always has
        something to show without fabricating Gemini output.
    """
    import streamlit as st
    from state.fleet_state import Fleet, FleetStatus, initialize_session_state

    initialize_session_state()

    existing = None
    for f in st.session_state.get("active_fleets", []):
        if f.source == "live" and f.dock_number == 1:
            existing = f
            break

    if existing is None:
        fleet = Fleet(
            id="TK-MONITOR-D1",
            dock_number=1,
            truck_dimensions=(2.0, 2.0, 4.0),
            manifest=[],
            packing_layout={
                'layout': {
                    'part_number': 'Truck-Dock1',
                    'WHD': (200.0, 200.0, 400.0),
                    'packed_items': [],
                    'unfitted_items': [],
                    'gravity': [0, 0, 0, 0],
                },
                'manifest_summary': [],
                'total_items_expected': 0,
                'packed_count': 0,
                'unfitted_count': 0,
                'fill_percentage': 0.0,
            },
            status=FleetStatus.LOADING,
            fill_percentage=0.0,
            truck_name="Truck-Dock1",
            loading_in_progress=False,
            doors_closing=False,
            truck_moving=False,
            source="live",
        )
        fleet.cctv_frame_path = mock_fleet_factory.ensure_dock_assets(1)
        st.session_state.active_fleets.append(fleet)
        upsert_dock_fleet(1, fleet.id)
        set_dock_stage(1, DockStage.MONITORED)
        set_analysis_source(1, AnalysisSource.NONE)
    else:
        # Existing live fleet — refresh asset pairing only, do not overwrite
        existing.cctv_frame_path = mock_fleet_factory.ensure_dock_assets(1)
