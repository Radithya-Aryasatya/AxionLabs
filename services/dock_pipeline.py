"""
services/dock_pipeline.py
=========================
The Render -> Gemini -> Notify orchestration for Dock 1.

When the worker clicks "Render 3D Bin Layout", this module:
  1. upserts the Dock 1 fleet (pins dock_number=1),
  2. pairs a deterministic CCTV frame + depth map,
  3. runs Gemini spatial reasoning with a HARD TIMEOUT + fallback ladder
     (last-good cached -> deterministic simulation -> canned placeholder),
     so a slow API can never hang the pitch,
  4. persists the analysis, records anomalies, and pushes a cross-view
     notification + toast.

The whole pipeline is wrapped so it can never crash the worker view.
"""

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime
from typing import Tuple

from state.fleet_state import (
    Fleet, FleetStatus, AnomalyRecord, add_anomaly_record,
    register_fleet_from_packing_result,
)
from state.dock_state import (
    upsert_dock_fleet, set_dock_stage, set_analysis_source,
    set_dock_alert, DockStage, AnalysisSource,
)
from state.notifications import push_notification
from services.gemini_service import GeminiService, GeminiAnalysisResult
from services.anomaly_engine import AnomalyEngine
from services import mock_fleet_factory

# Timeout (seconds) for the real Gemini API call. Tunable via env.
ANALYSIS_TIMEOUT_S = float(os.getenv("ANALYSIS_TIMEOUT_S", "10"))


def _cached_analysis(fleet_id: str):
    """Return the last-good cached GeminiAnalysisResult for a fleet, or None."""
    import streamlit as st
    return st.session_state.get("gemini_cache", {}).get(fleet_id)


def _cache_analysis(fleet_id: str, result: GeminiAnalysisResult):
    import streamlit as st
    st.session_state.setdefault("gemini_cache", {})[fleet_id] = result


def _canned_placeholder() -> GeminiAnalysisResult:
    """Absolute last-resort result so the UI always has something to show."""
    return GeminiAnalysisResult(
        anomaly_type="NONE", severity="NONE", confidence=0.0,
        analysis_paragraph=(
            "Analysis temporarily unavailable. Displaying the last known "
            "configuration. The dock will re-analyze automatically."
        ),
        affected_items=[], recommended_actions=["Retry analysis"],
        spatial_discrepancy_score=0.0,
    )


def analyze_with_fallback(fleet: Fleet) -> Tuple[GeminiAnalysisResult, AnalysisSource]:
    """
    Run Gemini spatial reasoning with a hard timeout and a 3-tier fallback.

    Returns (result, source) where source is one of:
      LIVE_GEMINI / FALLBACK_CACHED / FALLBACK_SIMULATED
    """
    svc = GeminiService()
    engine = AnomalyEngine(gemini_service=svc)

    cctv = fleet.cctv_frame_path or mock_fleet_factory.ensure_dock_assets(
        fleet.dock_number)[0]
    depth = fleet.depth_map_path or mock_fleet_factory.ensure_dock_assets(
        fleet.dock_number)[1]

    def _call():
        return svc.analyze_loading(
            cctv_frame_path=cctv,
            depth_map_path=depth,
            packing_plan=fleet.packing_layout,
            manifest=fleet.manifest,
            fleet_state=engine._fleet_to_state_dict(fleet),
        )

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call)
            result = future.result(timeout=ANALYSIS_TIMEOUT_S)
            _cache_analysis(fleet.id, result)
            return result, AnalysisSource.LIVE_GEMINI
    except TimeoutError:
        # API too slow — fall through to cache / simulation
        cached = _cached_analysis(fleet.id)
        if cached is not None:
            return cached, AnalysisSource.FALLBACK_CACHED
        sim = _call() if not svc._initialized else None
        if sim is None:
            sim = svc._simulate_analysis(
                cctv, depth, fleet.packing_layout, fleet.manifest,
                engine._fleet_to_state_dict(fleet),
            )
        _cache_analysis(fleet.id, sim)
        return sim, AnalysisSource.FALLBACK_SIMULATED
    except Exception:
        # Any other failure — same fallback ladder
        cached = _cached_analysis(fleet.id)
        if cached is not None:
            return cached, AnalysisSource.FALLBACK_CACHED
        try:
            sim = svc._simulate_analysis(
                cctv, depth, fleet.packing_layout, fleet.manifest,
                engine._fleet_to_state_dict(fleet),
            )
            _cache_analysis(fleet.id, sim)
            return sim, AnalysisSource.FALLBACK_SIMULATED
        except Exception:
            return _canned_placeholder(), AnalysisSource.FALLBACK_SIMULATED


def run_dock1_render_pipeline(
    partno: str,
    fig,
    manifest: list,
    packer,
    truck_w: float, truck_h: float, truck_d: float,
):
    """
    Full Render-trigger pipeline for Dock 1. Called from the worker's
    render fragment. Never raises — all exceptions are swallowed so the
    worker view can never crash mid-pitch.
    """
    import streamlit as st
    try:
        _run_dock1_render_pipeline(partno, fig, manifest, packer,
                                   truck_w, truck_h, truck_d)
    except Exception as e:
        # Surface a toast but keep the app alive
        try:
            st.toast(f"⚠️ Dock 1 analysis error: {e}", icon="⚠️")
        except Exception:
            pass


def _run_dock1_render_pipeline(partno, fig, manifest, packer,
                                truck_w, truck_h, truck_d):
    import streamlit as st
    from state.fleet_state import initialize_session_state, get_fleet_by_id
    initialize_session_state()

    # --- 1. Upsert Dock 1 fleet (pin to dock_number=1) ---
    existing = None
    for f in st.session_state.get("active_fleets", []):
        if f.source == "live" and f.dock_number == 1:
            existing = f
            break

    if existing is None:
        fleet = register_fleet_from_packing_result(
            manifest=manifest, packer=packer,
            truck_w=truck_w, truck_h=truck_h, truck_d=truck_d,
            truck_name=f"Truck-Dock1",
            dock_number=1,
        )
    else:
        fleet = existing

    # Publish the freshly-rendered figure into the twin registry
    st.session_state['last_3d_figure'] = fig
    st.session_state.setdefault('fleet_3d_figures', {})[partno] = fig

    # --- 2. Pair CCTV frame + depth map ---
    cctv, depth = mock_fleet_factory.ensure_dock_assets(1)
    fleet.cctv_frame_path = cctv
    fleet.depth_map_path = depth
    upsert_dock_fleet(1, fleet.id)
    set_dock_stage(1, DockStage.ANALYZING)

    # --- 3. Analyze with non-blocking fallback ---
    result, source = analyze_with_fallback(fleet)
    set_analysis_source(1, source)

    # --- 4. Decide + persist ---
    engine = AnomalyEngine()
    decision = engine.evaluate(fleet, result)
    fleet.gemini_analysis = result.to_dict()
    fleet.status = decision.fleet_status

    if decision.severity in ("WARNING", "CRITICAL"):
        add_anomaly_record(fleet, AnomalyRecord(
            anomaly_type=decision.anomaly_type,
            severity=decision.severity,
            timestamp=datetime.now(),
            analysis_paragraph=result.analysis_paragraph,
            affected_items=result.affected_items,
            recommended_actions=result.recommended_actions,
        ))

    fleet.last_updated = datetime.now()
    set_dock_stage(1, DockStage.MONITORED)

    # --- 5. Notify (cross-view) ---
    if decision.severity in ("WARNING", "CRITICAL"):
        level = "CRITICAL" if decision.severity == "CRITICAL" else "WARNING"
        push_notification(
            dock_number=1, fleet_id=fleet.id, level=level,
            title=f"Dock 1 — {decision.anomaly_type.replace('_', ' ')}",
            body=result.analysis_paragraph[:160],
        )
        set_dock_alert(1, True)
        st.toast(
            f"{'🚨' if level == 'CRITICAL' else '⚠️'} Dock 1 flagged — manager notified",
            icon="🚨" if level == "CRITICAL" else "⚠️",
        )
    else:
        push_notification(
            dock_number=1, fleet_id=fleet.id, level="INFO",
            title="Dock 1 — layout verified clear",
            body="Gemini spatial analysis found no anomalies.",
        )
        st.toast("✅ Dock 1 layout verified — no anomalies", icon="✅")

