"""
services/scan_orchestrator.py
==============================
Centralized multi-dock scanning orchestrator (Task 4).

Implements the "SCAN ALL DOCKS" workflow:

    Executive Dashboard
        SCAN ALL DOCKS button
            -> run_scan_all_docks()
                for dock in [1, 2, 3, 4] (SEQUENTIAL - quota-conscious):
                    1. resolve context (CCTV primary, digital twin secondary)
                    2. guard: CCTV file must exist (no API call otherwise)
                    3. analyze_with_fallback (hard timeout, per-dock retry)
                    4. per-dock persistence (isolated - one failure never blocks others)
                    5. record outcome in the scan_summary ledger

Design contract
---------------
* The ACTUAL CCTV image is the PRIMARY input to Gemini. The virtual digital
  twin is SECONDARY comparison context. Dock 1 before worker render has no
  twin - it is scanned CCTV-only.
* Docks 2-4 already have predetermined Digital Twins (mock layouts) and can
  pass both CCTV + twin.
* Per-dock isolation: a failed Gemini request for one dock NEVER prevents
  the other docks from being analyzed. Honest FAILED results are preserved.
* Sequential processing to avoid parallel RPM pressure on the Gemini API.
* Pre-guard: no API call when the CCTV image is missing (quota-safe).
"""

import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

from state.fleet_state import Fleet, FleetStatus, AnomalyRecord
from state.dock_state import (
    get_dock_state, set_dock_stage, set_analysis_source,
    set_dock_alert, mark_dock_scanned,
    DockStage, AnalysisSource,
)
from state.notifications import push_notification
from services.gemini_service import GeminiAnalysisResult, STATUS_SUCCESS, STATUS_FAILED
from services.dock_pipeline import analyze_with_fallback
from services.anomaly_engine import AnomalyEngine

log = logging.getLogger("scan_orchestrator")

# Per-dock retry budget for the centralized scan (only applied to docks that
# returned an honest FAILED). Tunable via env. 0 = no retry.
SCAN_ALL_RETRIES = int(os.getenv("SCAN_ALL_RETRIES", "1"))


def _resolve_dock_context(dock_number):
    from services.cctv_manager import resolve_dock_cctv

    fleet = None
    import streamlit as st
    dock_state = get_dock_state(dock_number)
    if dock_state is not None:
        fleet = dock_state.fleet()

    cctv_path = ""
    depth_path = ""
    twin_path = None

    if fleet is not None:
        cctv_path = resolve_dock_cctv(dock_number)
        depth_path = fleet.depth_map_path or ""
        try:
            from services.virtual_camera import render_virtual_cctv_for_fleet
            twin_path = render_virtual_cctv_for_fleet(fleet)
        except Exception:
            twin_path = None

    return {
        "dock_number": dock_number,
        "fleet": fleet,
        "cctv_path": cctv_path,
        "depth_path": depth_path,
        "twin_path": twin_path,
        "has_twin": bool(twin_path),
    }


def _add_anomaly_safe(fleet, record):
    try:
        from state.fleet_state import add_anomaly_record
        add_anomaly_record(fleet, record)
    except Exception:
        if not hasattr(fleet, "anomaly_history") or fleet.anomaly_history is None:
            fleet.anomaly_history = []
        fleet.anomaly_history.append(record)


def _persist_result(outcome, fleet, dock_number, result, source):
    try:
        engine = AnomalyEngine()
        decision = engine.evaluate(fleet, result)
        fleet.gemini_analysis = result.to_dict()
        fleet.status = decision.fleet_status

        if decision.severity in ("WARNING", "CRITICAL"):
            _add_anomaly_safe(fleet, AnomalyRecord(
                anomaly_type=decision.anomaly_type,
                severity=decision.severity,
                timestamp=datetime.now(),
                analysis_paragraph=result.analysis_paragraph,
                affected_items=result.affected_items,
                recommended_actions=result.recommended_actions,
            ))

        fleet.last_updated = datetime.now()
        set_dock_stage(dock_number, DockStage.MONITORED)
        set_analysis_source(dock_number, source)

        if decision.severity in ("WARNING", "CRITICAL"):
            level = "CRITICAL" if decision.severity == "CRITICAL" else "WARNING"
            push_notification(
                dock_number=dock_number, fleet_id=fleet.id, level=level,
                title=f"Dock {dock_number} - {decision.anomaly_type.replace('_', ' ')}",
                body=result.analysis_paragraph[:160],
            )
            set_dock_alert(dock_number, True)
        else:
            push_notification(
                dock_number=dock_number, fleet_id=fleet.id, level="INFO",
                title=f"Dock {dock_number} - layout verified clear",
                body="Gemini spatial analysis found no anomalies.",
            )

        outcome["severity"] = decision.severity or result.severity or "NONE"
        outcome["analysis"] = fleet.gemini_analysis
    except Exception as exc:
        outcome["error"] = f"persist-error: {exc}"
        outcome["status"] = "FAILED"
        set_dock_stage(dock_number, DockStage.MONITORED)


def _persist_failure(outcome, fleet, dock_number, error_msg):
    try:
        fleet.gemini_analysis = GeminiAnalysisResult(
            anomaly_type="GEMINI_REQUEST_FAILED",
            severity="NONE",
            confidence=0.0,
            analysis_paragraph="",
            status=STATUS_FAILED,
            model="",
            raw_response="",
            error=error_msg or "Unknown error",
        ).to_dict()
        fleet.last_updated = datetime.now()
        set_dock_stage(dock_number, DockStage.MONITORED)
        set_analysis_source(dock_number, AnalysisSource.GEMINI_FAILED)
        set_dock_alert(dock_number, True)
        push_notification(
            dock_number=dock_number, fleet_id=fleet.id, level="WARNING",
            title=f"Dock {dock_number} - Gemini analysis FAILED",
            body=(error_msg or "Unknown error")[:160],
        )
        outcome["analysis"] = fleet.gemini_analysis
    except Exception:
        pass
    finally:
        mark_dock_scanned(dock_number)


def _scan_single_dock(ctx, retry_left=SCAN_ALL_RETRIES):
    dock_number = ctx["dock_number"]
    fleet = ctx["fleet"]
    cctv_path = ctx["cctv_path"]
    twin_path = ctx["twin_path"]

    outcome = {
        "dock_number": dock_number,
        "status": "FAILED",
        "source": AnalysisSource.NONE.value,
        "twin_used": ctx["has_twin"],
        "severity": "NONE",
        "error": "",
        "analysis": {},
    }

    if fleet is None:
        outcome["status"] = "SKIP_NO_FLEET"
        outcome["error"] = f"No fleet registered for Dock {dock_number}"
        return outcome

    if not cctv_path or not os.path.isfile(cctv_path):
        outcome["status"] = "SKIP_NO_CCTV"
        outcome["error"] = f"No CCTV image available for Dock {dock_number}"
        _persist_failure(outcome, fleet, dock_number,
                         "No CCTV image available - scan skipped (no API call made)")
        return outcome

    set_dock_stage(dock_number, DockStage.ANALYZING)

    try:
        result, source = analyze_with_fallback(fleet, virtual_cctv_path=twin_path)

        if result.status == STATUS_FAILED and retry_left > 0:
            log.info("Dock %d FAILED - retrying (%d left)", dock_number, retry_left)
            time.sleep(1.0)
            result, source = analyze_with_fallback(fleet, virtual_cctv_path=twin_path)

        outcome["source"] = source.value
        outcome["twin_used"] = ctx["has_twin"] and bool(twin_path)

        if result.status == STATUS_FAILED:
            outcome["status"] = "FAILED"
            outcome["error"] = result.error or "Unknown Gemini error"
            _persist_failure(outcome, fleet, dock_number, result.error)
            return outcome

        outcome["status"] = "SUCCESS" if result.status == STATUS_SUCCESS else "SIMULATED"
        outcome["severity"] = result.severity or "NONE"
        _persist_result(outcome, fleet, dock_number, result, source)
        return outcome

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        log.error("Dock %d scan error: %s", dock_number, error_msg)
        outcome["status"] = "FAILED"
        outcome["error"] = error_msg
        _persist_failure(outcome, fleet, dock_number, error_msg)
        return outcome


def run_scan_all_docks():
    import streamlit as st

    outcomes = {}
    for dock_number in (1, 2, 3, 4):
        ctx = _resolve_dock_context(dock_number)
        outcome = _scan_single_dock(ctx)
        outcomes[dock_number] = outcome
        mark_dock_scanned(dock_number)

    st.session_state["scan_summary"] = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "outcomes": outcomes,
    }
    return outcomes


def get_scan_summary():
    import streamlit as st
    return st.session_state.get("scan_summary")


def reset_scan_summary():
    import streamlit as st


    st.session_state.pop("scan_summary", None)

