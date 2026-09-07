"""
executive_dashboard.py
=======================
Executive Control Tower — Main View 2 controller.

Landing view for the Manager role. Displays:
  - Persistent anomaly alert banners (all active fleets)
  - 4-dock fixed grid (Dock 1 LIVE, Docks 2–4 editable placeholder pages)
  - 3-dock fixed grid (Dock 1 LIVE, Docks 2 & 3 MOCK demo data)
  - Tri-View Detail Inspection Panel (when a fleet is selected)

Note: This file is named with underscore (executive_dashboard.py) so it can
be imported as a Python module. The original executive-dashboard.py (with
hyphen) has been superseded by this version.
"""

import streamlit as st
from state.fleet_state import get_fleet_by_id
from state.dock_state import get_all_docks
from components.fleet_card import render_fleet_card_compact
from components.anomaly_banner import render_anomaly_banners
from components.tri_view_panel import render_tri_view_panel
from services.mock_fleet_factory import seed_mock_docks
from services.dock_pipeline import ensure_dock1_monitor_fleet


def render_executive_dashboard():
    """
    Main entry point for the Executive Control Tower view.
    Call this from app.py when view_mode == 'executive'.
    """
    # Ensure placeholder mock docks exist (Docks 2, 3, 4)
    seed_mock_docks()
    ensure_dock1_monitor_fleet()

    # --- In-dashboard alert corner (top-right, control-room style) ---
    from components.alert_corner import render_alert_corner
    from components.alert_corner import render_alert_corner
    render_alert_corner()

    # Task 4: restore operator's CCTV selections after seeding (seeding
    # would otherwise overwrite them with deterministic placeholders).
    from services.cctv_manager import apply_cctv_selections
    apply_cctv_selections()
    render_alert_corner()

    # Page header
    st.markdown("""
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 20px;">
            <div style="font-size: 32px;">🛰️</div>
            <div>
                <h1 style="margin: 0; color: #ffffff;">Executive Control Tower</h1>
                <p style="margin: 4px 0; color: #94A3B8; font-size: 13px;">
                    Hybrid Fleet Monitoring & Diagnostic Dashboard
                </p>
            </div>
        </div>
    """, unsafe_allow_html=True)

    fleets = st.session_state.get('active_fleets', [])

    if not fleets:
        _render_empty_state()
        return

    # --- Active Anomaly Banners ---
    render_anomaly_banners()

    # Task 4: Centralized SCAN ALL DOCKS control panel.
    _render_scan_all_control()

    # --- Fleet Status Summary ---
    render_anomaly_banners()

    # --- Fleet Status Summary ---
    _render_status_summary(fleets)

    st.markdown("---")

    # --- Tri-View Detail Panel (if a fleet is selected) ---
    selected_id = st.session_state.get('selected_fleet_id')
    selected_fleet = get_fleet_by_id(selected_id) if selected_id else None

    if selected_fleet:
        render_tri_view_panel(selected_fleet)
        # --- 4-Dock Fixed Grid ---
    else:
        # --- 3-Dock Fixed Grid ---
        _render_dock_grid()

    # --- Demo reset control ---
    with st.expander("🔁 Demo Controls", expanded=False):
        st.caption("Reset Docks 2, 3, 4 to their opening demo state.")
        if st.button("Reset Mock Docks", key="reset_mock_docks"):
            from services.mock_fleet_factory import reseed_mock_docks
            reseed_mock_docks()
            st.rerun()

def _render_scan_all_control():
    """
    Task 4: Centralized "SCAN ALL DOCKS" control panel.

    Lets the operator prepare the dock CCTV inputs (via per-dock change
    controls in the grid below) and then trigger a single fleet-wide scan.
    The scan is sequential and quota-conscious, with per-dock isolation.
    """
    from services.scan_orchestrator import run_scan_all_docks, get_scan_summary

    st.markdown("### 🔍 Centralized Scan Control")
    st.caption(
        "Analyze the current CCTV state of all four docks. Each dock is scanned "
        "independently — one failure never blocks the others. To change a dock's "
        "CCTV image, investigate that dock individually first."
    )

    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button(
            "🛰️ SCAN ALL DOCKS",
            key="scan_all_docks",
            type="primary",
            use_container_width=True,
            help="Analyze the current CCTV state of all four docks through Gemini. "
                 "The actual CCTV image is the PRIMARY input; the digital twin "
                 "(when available) is secondary comparison context.",
        ):
            with st.spinner("Scanning all docks — sequential, quota-conscious..."):
                run_scan_all_docks()
            st.rerun()

    with c2:
        summary = get_scan_summary()
        if summary is None:
            st.info("No scan has been run yet. Change any dock's CCTV image, then press SCAN ALL DOCKS.")
        else:
            when = summary.get("at", "?")
            outcomes = summary.get("outcomes", {})
            parts = []
            for dn in sorted(outcomes):
                o = outcomes[dn]
                status = o.get("status", "?")
                if status == "SUCCESS":
                    sev = o.get("severity", "NONE")
                    if sev == "NONE":
                        chip = f"✅ Dock {dn}: CLEAR"
                    else:
                        chip = f"⚠️ Dock {dn}: {sev}"
                elif status == "SIMULATED":
                    chip = f"🧪 Dock {dn}: SIMULATED"
                elif status == "SKIP_NO_CCTV":
                    chip = f"📷 Dock {dn}: NO CCTV"
                elif status == "SKIP_NO_FLEET":
                    chip = f"🚫 Dock {dn}: NO FLEET"
                else:
                    chip = f"❌ Dock {dn}: FAILED"
                parts.append(chip)
            st.markdown(f"**Last scan:** `{when}`")
            st.markdown(" · ".join(parts))

    st.markdown("---")

def _render_dock_grid():
    """Render the 4 fixed docks as a column grid."""
    st.markdown("### 🏗️ Loading Dock Overview")
    docks = get_all_docks()
    cols = st.columns(4)
    for i, dn in enumerate(sorted(docks)):
        dock = docks[dn]
        with cols[i]:
            render_fleet_card_compact(dock.fleet())

            # Task 4: scan-state chip only. The dashboard is a monitoring/navigation
            # surface — it must NOT expose any CCTV-replacement control. The
            # "Change CCTV Image" workflow exists solely in the individual dock
            # screening view (components/tri_view_panel.py).
            from state.dock_state import get_dock_scan_state
            scan_state = get_dock_scan_state(dn)
            chip = f"Dock {dn}: {scan_state.get('state', '—')}"
            if scan_state.get("stale"):
                chip += " · STALE"
            st.caption(chip)

    

def _render_status_summary(fleets):
    """Render a quick summary of fleet statuses."""
    status_counts = {
        'LOADING': 0,
        'INSPECTED - CLEAR': 0,
        'ANOMALY DETECTED': 0,
        'BLOCKED FROM DEPARTURE': 0,
    }

    for fleet in fleets:
        status_val = fleet.status.value
        if status_val in status_counts:
            status_counts[status_val] += 1
        elif status_val == "PAUSED / AUDIT REQUIRED":
            status_counts['ANOMALY DETECTED'] += 1

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Loading", status_counts['LOADING'])
    with col2:
        st.metric("Cleared", status_counts['INSPECTED - CLEAR'])
    with col3:
        st.metric("Anomaly", status_counts['ANOMALY DETECTED'])
    with col4:
        st.metric("Blocked", status_counts['BLOCKED FROM DEPARTURE'])


def _render_empty_state():
    """Render an empty state when no fleets are available."""
    st.markdown("""
        <div style="
            text-align: center;
            padding: 60px;
            background: #1e293b;
            border-radius: 12px;
            border: 2px dashed #475569;
        ">
            <div style="font-size: 48px; margin-bottom: 16px;">📭</div>
            <h3 style="color: #94A3B8; margin-bottom: 8px;">No Active Fleets</h3>
            <p style="color: #64748b; font-size: 13px;">
                Fleet plans created in the Loading Planner (View 1) will appear
                here as active fleets automatically.
            </p>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("""
        <div style="text-align: center; padding: 20px; color: #64748b; font-size: 12px;">
            <p><strong>Demo Mode:</strong> Switch to Worker/Planner view, create a packing plan,</p>
            <p>and it will auto-register as a fleet in the Executive Control Tower.</p>
        </div>
    """, unsafe_allow_html=True)
