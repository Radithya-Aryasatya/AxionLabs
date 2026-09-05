"""
services/dock_pipeline.py
=========================
The Render -> Gemini -> Notify orchestration for Dock 1.

When the worker clicks "Render 3D Bin Layout", this module:
  1. upserts the Dock 1 fleet (pins dock_number=1),
  2. pairs a deterministic CCTV frame + depth map,
  3. runs REAL Gemini spatial reasoning with a hard timeout,
  4. persists the analysis, records anomalies, and pushes a cross-view
     notification + toast.

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
from datetime import datetime
from typing import Optional, Tuple

from state.fleet_state import (
    Fleet, FleetStatus, AnomalyRecord, add_anomaly_record,
    register_fleet_from_packing_result,
)
from state.dock_state import (
    upsert_dock_fleet, set_dock_stage, set_analysis_source,
    set_dock_alert, DockStage, AnalysisSource,
)
from state.notifications import push_notification
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


def _cache_analysis(fleet_id: str, result: GeminiAnalysisResult):
    """Cache a SUCCESSFUL live result for telemetry/inspection purposes only —
    cached data is never substituted for a live or failed request."""
    import streamlit as st
    st.session_state.setdefault("gemini_cache", {})[fleet_id] = result


def _failed_from_exception(svc: GeminiService, exc: Exception) -> GeminiAnalysisResult:
    """Wrap an unexpected pipeline error as an honest FAILED result."""
    return GeminiAnalysisResult(
        anomaly_type="OTHER", severity="NONE", confidence=0.0,
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
        fleet.dock_number)[0]
    depth = fleet.depth_map_path or mock_fleet_factory.ensure_dock_assets(
        fleet.dock_number)[1]

    # Normalize the twin path: only pass it when the file actually exists.
    twin = virtual_cctv_path if (virtual_cctv_path and os.path.isfile(virtual_cctv_path)) else ""

    def _call():
        return svc.analyze_loading(
            cctv_frame_path=cctv,
            depth_map_path=depth,
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
            anomaly_type="OTHER", severity="NONE", confidence=0.0,
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
        _cache_analysis(fleet.id, result)
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
        CCTV/depth-map pairing is refreshed.
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
        cctv, depth = mock_fleet_factory.ensure_dock_assets(1)
        fleet.cctv_frame_path = cctv
        fleet.depth_map_path = depth
        st.session_state.active_fleets.append(fleet)
        upsert_dock_fleet(1, fleet.id)
        set_dock_stage(1, DockStage.MONITORED)
        set_analysis_source(1, AnalysisSource.NONE)
    else:
        # Existing live fleet — refresh asset pairing only, do not overwrite
        cctv, depth = mock_fleet_factory.ensure_dock_assets(1)
        existing.cctv_frame_path = cctv
        existing.depth_map_path = depth


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
    from state.fleet_state import initialize_session_state
    initialize_session_state()

    # --- 1. Upsert Dock 1 fleet (pin to dock_number=1) ---
    # register_fleet_from_packing_result handles upsert: if a
    # live Dock-1 fleet already exists (e.g. the monitor
    # placeholder), it is updated in place with the new packing
    # layout; otherwise a new fleet is created.
    fleet = register_fleet_from_packing_result(
        manifest=manifest, packer=packer,
        truck_w=truck_w, truck_h=truck_h, truck_d=truck_d,
        truck_name="Truck-Dock1",
        dock_number=1,
    )
    if fleet is None:
        st.toast("⚠️ No bins in packing result - Dock 1 not updated", icon="⚠️")
        return

    # Publish the freshly-rendered figure into the twin registry
    st.session_state['last_3d_figure'] = fig
    st.session_state.setdefault('fleet_3d_figures', {})[partno] = fig

    # --- 2. Pair CCTV frame + depth map ---
    cctv, depth = mock_fleet_factory.ensure_dock_assets(1)
    fleet.cctv_frame_path = cctv
    fleet.depth_map_path = depth

    # Task 4: if the operator already chose a replacement CCTV image for
    # Dock 1, restore it — asset pairing above would otherwise overwrite
    # the selection with the deterministic placeholder.
    from services.cctv_manager import restore_dock_cctv_selection
    operator_cctv = restore_dock_cctv_selection(1)
    if operator_cctv and os.path.isfile(operator_cctv):
        fleet.cctv_frame_path = operator_cctv

    upsert_dock_fleet(1, fleet.id)
    set_dock_stage(1, DockStage.ANALYZING)

    # --- 3. Analyze with non-blocking fallback ---
    # Task 4: pass the SECONDARY digital-twin context when available. After
    # the worker renders, Dock 1 has a layout -> twin can be rendered.
    twin_path = None
    try:
        from services.virtual_camera import render_virtual_cctv_for_fleet
        twin_path = render_virtual_cctv_for_fleet(fleet)
    except Exception:
        twin_path = None

    result, source = analyze_with_fallback(fleet, virtual_cctv_path=twin_path)
    set_analysis_source(1, source)

    # --- 3b. Failed Gemini request: surface the failure honestly ---
    # No simulated substitute, no "verified clear" notification, no anomaly
    # records derived from default values.
    if getattr(result, "status", "") == STATUS_FAILED:
        fleet.gemini_analysis = result.to_dict()
        fleet.last_updated = datetime.now()
        set_dock_stage(1, DockStage.MONITORED)
        set_dock_alert(1, True)
        push_notification(
            dock_number=1, fleet_id=fleet.id, level="WARNING",
            title="Dock 1 — Gemini analysis FAILED",
            body=(result.error or "Unknown Gemini error")[:160],
        )
        st.toast("❌ Dock 1 Gemini analysis failed — see audit panel", icon="❌")
        return

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

