"""
state/dock_state.py
====================
Hybrid dock state model for the Executive Fleet Diagnostic Center.

DockState is the dock-level operational wrapper that View 1 (worker) writes
and View 2 (executive) reads. It sits on top of the existing Fleet dataclass
(which remains the cargo/audit model) and is stored entirely in
st.session_state as structured dataclasses/enums.

Registry layout in session state:
    st.session_state.dock_registry: Dict[int, DockState]
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Optional


class DockKind(Enum):
    """Whether a dock is worker-driven or deterministic demo data."""
    LIVE = "LIVE"      # Dock 1 — connected to the Worker Interface
    MOCK = "MOCK"      # Docks 2, 3, 4 — editable placeholder demo data


class DockStage(Enum):
    """Operational stage of a dock (drives the status ticker + card LED)."""
    AWAITING_RENDER = "AWAITING RENDER"
    LOADING = "LOADING"
    ANALYZING = "GEMINI ANALYZING"
    MONITORED = "MONITORED"


class AnalysisSource(Enum):
    """Where the current Gemini analysis came from (shown as a chip in the audit panel)."""
    NONE = "—"
    LIVE_GEMINI = "LIVE GEMINI"
    GEMINI_FAILED = "GEMINI FAILED"
    FALLBACK_CACHED = "CACHED"
    FALLBACK_SIMULATED = "SIMULATED"


@dataclass
class DockState:
    """
    Operational state of a single loading dock.

    The linked Fleet (looked up via fleet_id) holds cargo/audit data;
    this wrapper holds dock-level lifecycle + notification state.
    """
    dock_number: int
    kind: DockKind
    fleet_id: Optional[str] = None
    stage: DockStage = DockStage.AWAITING_RENDER
    analysis_source: AnalysisSource = AnalysisSource.NONE
    last_event_at: datetime = field(default_factory=datetime.now)
    unread_alert: bool = False
    # --- Task 4: CCTV replacement + centralized scan lifecycle ---
    # Timestamp of the last operator CCTV image replacement for this dock.
    # A CCTV change NEVER triggers analysis; it only invalidates the previous
    # scan result (stale when cctv_updated_at > last_scan_at).
    cctv_updated_at: Optional[datetime] = None
    # Timestamp of the last completed centralized/per-dock Gemini scan.
    last_scan_at: Optional[datetime] = None

    def fleet(self):
        """Resolve the linked Fleet from session state (or None)."""
        if not self.fleet_id:
            return None
        from state.fleet_state import get_fleet_by_id
        return get_fleet_by_id(self.fleet_id)


# --- REGISTRY HELPERS (all operate on st.session_state) ---

def initialize_dock_registry():
    """
    Seed dock_registry with the 4 fixed docks if not already present.
    Called from initialize_session_state() in fleet_state.py.
    Force-seeds if the registry is empty or missing (handles bare-Python
    test mode where st.session_state.clear() may not function).
    """
    import streamlit as st
    registry = st.session_state.get('dock_registry')
    if registry and len(registry) >= 4:
        return
    st.session_state.dock_registry = {
        1: DockState(dock_number=1, kind=DockKind.LIVE,
                     stage=DockStage.AWAITING_RENDER),
        2: DockState(dock_number=2, kind=DockKind.MOCK,
                     stage=DockStage.MONITORED),
        3: DockState(dock_number=3, kind=DockKind.MOCK,
                     stage=DockStage.MONITORED),
        4: DockState(dock_number=4, kind=DockKind.MOCK,
                     stage=DockStage.MONITORED),
    }
    # Track which dock numbers are reserved for mocks (so live fleets never collide)
    st.session_state["mock_dock_numbers"] = {2, 3, 4}


def get_dock_state(dock_number: int) -> Optional[DockState]:
    """Retrieve a DockState by dock number."""
    import streamlit as st
    return st.session_state.get('dock_registry', {}).get(dock_number)


def get_all_docks() -> Dict[int, DockState]:
    """Return the full dock registry dict."""
    import streamlit as st
    return st.session_state.get('dock_registry', {})


def register_dock_fleet(dock_number: int, fleet_id: str):
    """Register a Fleet to a dock, creating the DockState if needed."""
    import streamlit as st
    dock = get_dock_state(dock_number)
    if dock is None:
        kind = DockKind.LIVE if dock_number == 1 else DockKind.MOCK
        dock = DockState(
            dock_number=dock_number,
            kind=kind,
        )
        st.session_state.dock_registry[dock_number] = dock
    dock.fleet_id = fleet_id
    dock.last_event_at = datetime.now()
    st.session_state.dock_registry[dock_number] = dock


def upsert_dock_fleet(dock_number: int, fleet_id: str):
    """Link a Fleet to a dock and stamp the event time."""
    import streamlit as st
    dock = get_dock_state(dock_number)
    if dock is None:
        return
    dock.fleet_id = fleet_id
    dock.last_event_at = datetime.now()
    st.session_state.dock_registry[dock_number] = dock


def set_dock_stage(dock_number: int, stage: DockStage):
    """Update a dock's operational stage and stamp the event time."""
    import streamlit as st
    dock = get_dock_state(dock_number)
    if dock is None:
        return
    dock.stage = stage
    dock.last_event_at = datetime.now()
    st.session_state.dock_registry[dock_number] = dock


def set_analysis_source(dock_number: int, source: AnalysisSource):
    """Record where the current analysis came from."""
    import streamlit as st
    dock = get_dock_state(dock_number)
    if dock is None:
        return
    dock.analysis_source = source
    st.session_state.dock_registry[dock_number] = dock


def set_dock_alert(dock_number: int, unread: bool):
    """Toggle the unread-alert flag (drives card LED + bell badge)."""
    import streamlit as st
    dock = get_dock_state(dock_number)
    if dock is None:
        return
    dock.unread_alert = unread
    dock.last_event_at = datetime.now()
    st.session_state.dock_registry[dock_number] = dock


def clear_all_dock_alerts():
    """Mark every dock's alert as read."""
    import streamlit as st
    registry = st.session_state.get('dock_registry', {})
    for dock in registry.values():
        dock.unread_alert = False


# --- TASK 4: CCTV replacement + centralized scan lifecycle -------------------

def mark_dock_cctv_changed(dock_number: int):
    """Stamp the dock as having a replaced CCTV input.

    Called by the CCTV replacement flow ONLY. Changing the image never
    triggers Gemini — it just invalidates the previous scan result so the
    dashboard can show a STALE chip until the next scan.
    """
    import streamlit as st
    dock = get_dock_state(dock_number)
    if dock is None:
        return
    dock.cctv_updated_at = datetime.now()
    dock.last_event_at = dock.cctv_updated_at
    st.session_state.dock_registry[dock_number] = dock


def mark_dock_scanned(dock_number: int):
    """Stamp the dock as scanned (scan completed: success OR honest failure)."""
    import streamlit as st
    dock = get_dock_state(dock_number)
    if dock is None:
        return
    dock.last_scan_at = datetime.now()
    dock.last_event_at = dock.last_scan_at
    st.session_state.dock_registry[dock_number] = dock


def reset_dock_scan_state(dock_number: int):
    """Clear the scan lifecycle timestamps (used by the demo reset control)."""
    import streamlit as st
    dock = get_dock_state(dock_number)
    if dock is None:
        return
    dock.cctv_updated_at = None
    dock.last_scan_at = None
    st.session_state.dock_registry[dock_number] = dock


def get_dock_scan_state(dock_number: int) -> Dict[str, object]:
    """
    Derive the current scan state of a dock from the EXISTING state fields
    (no new state system):

      NEVER_SCANNED  — analysis_source is NONE (no Gemini result yet)
      SCANNING       — dock stage is ANALYZING
      SUCCESS        — last result was a real (or simulated-offline) analysis
      FAILED         — last request failed (honest provenance preserved)

    plus a `stale` flag: True when the CCTV image was replaced after the
    last completed scan (the displayed result no longer reflects the
    current CCTV input).
    """
    dock = get_dock_state(dock_number)
    if dock is None:
        return {"state": "NEVER_SCANNED", "stale": False, "severity": "NONE"}

    stale = (
        dock.cctv_updated_at is not None
        and (dock.last_scan_at is None or dock.cctv_updated_at > dock.last_scan_at)
    )

    if dock.stage == DockStage.ANALYZING:
        return {"state": "SCANNING", "stale": stale, "severity": "NONE"}

    analysis = {}
    fleet = dock.fleet()
    if fleet is not None and isinstance(fleet.gemini_analysis, dict):
        analysis = fleet.gemini_analysis
    result_status = analysis.get("status", "")
    severity = str(analysis.get("severity", "NONE") or "NONE")

    if dock.analysis_source == AnalysisSource.GEMINI_FAILED or result_status == "FAILED":
        return {"state": "FAILED", "stale": stale, "severity": severity}

    if dock.analysis_source in (AnalysisSource.LIVE_GEMINI,
                                AnalysisSource.FALLBACK_SIMULATED,
                                AnalysisSource.FALLBACK_CACHED):
        return {"state": "SUCCESS", "stale": stale, "severity": severity}

    return {"state": "NEVER_SCANNED", "stale": stale, "severity": severity}
