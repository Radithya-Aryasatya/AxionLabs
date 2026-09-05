"""
executive_dashboard.py
=======================
Executive Control Tower — Main View 2 controller.

Landing view for the Manager role. Displays:
  - Persistent anomaly alert banners (all active fleets)
  - Auto-refreshing control-room status ticker
  - 4-dock fixed grid (Dock 1 LIVE, Docks 2–4 editable placeholder pages)
  - 3-dock fixed grid (Dock 1 LIVE, Docks 2 & 3 MOCK demo data)
  - Tri-View Detail Inspection Panel (when a fleet is selected)

Note: This file is named with underscore (executive_dashboard.py) so it can
be imported as a Python module. The original executive-dashboard.py (with
hyphen) has been superseded by this version.
"""

import streamlit as st
from state.fleet_state import Fleet, FleetStatus, get_fleet_by_id, select_fleet
from state.dock_state import get_all_docks, DockKind, DockStage
from components.fleet_card import render_fleet_card_compact
from components.anomaly_banner import render_anomaly_banners
from components.tri_view_panel import render_tri_view_panel
from components.status_ticker import render_status_ticker
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

    # --- Control-room status ticker (auto-refreshing) ---
    render_status_ticker()

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
        "Replace any dock's CCTV image above, then press the button below to "
        "analyze all four docks. Each dock is scanned independently — one "
        "failure never blocks the others."
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

            # Task 4: scan-state chip + per-dock CCTV change control.
            from state.dock_state import get_dock_scan_state
            scan_chip = get_dock_scan_state(dn)
            st.caption(scan_chip)

            with st.expander(f"📷 Change CCTV — Dock {dn}", expanded=False):
                from services.cctv_manager import render_cctv_change_control
                render_cctv_change_control(dn)

            # Select-for-investigation button
            if st.button(
                f"🔍 Investigate Dock {dn}",
                key=f"investigate_dock_{dn}",
                use_container_width=True,
            ):
                dock_fleet = dock.fleet()
                if dock_fleet is not None:
                    select_fleet(dock_fleet.id)
                    st.rerun()
    st.caption("Dock 1 is live from the Worker Interface • Docks 2, 3, 4 are editable placeholder pages")


def _render_dock_card(dock):
    """Render a single dock card with status LED, gauge, and open button."""
    fleet = dock.fleet()
    kind_label = "LIVE" if dock.kind == DockKind.LIVE else "DEMO"
    kind_color = "#3B82F6" if dock.kind == DockKind.LIVE else "#8B5CF6"

    if fleet:
        status_color = fleet.status.color
        status_text = fleet.status.value
        fill = fleet.fill_percentage
    else:
        status_color = "#6B7280"
        status_text = dock.stage.value
        fill = 0.0

    led_animation = ""
    if fleet:
        if fleet.status == FleetStatus.BLOCKED:
            led_animation = "animation:blink 0.8s infinite;"
        elif fleet.status == FleetStatus.ANOMALY_DETECTED:
            led_animation = "animation:blink 1.5s infinite;"

    alert_badge = (" <span style='background:#EF4444;color:white;border-radius:8px;"
                   "padding:0 6px;font-size:10px;'>ALERT</span>"
                   if dock.unread_alert else "")

    st.markdown(f"""
        <style>
        @keyframes blink {{ 0%,100%{{opacity:1;}} 50%{{opacity:0.2;}} }}
        </style>
        <div style="border:1px solid #334159;border-radius:12px;padding:16px;
                    background:linear-gradient(145deg,#1e293b,#0f172a);">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div>
                    <h3 style="margin:0;color:#fff;font-size:16px;">
                        🚛 Dock {dock.dock_number}{alert_badge}
                    </h3>
                    <span style="background:{kind_color};color:white;padding:2px 8px;
                                 border-radius:8px;font-size:10px;font-weight:700;">
                        {kind_label}
                    </span>
                </div>
                <div style="width:14px;height:14px;border-radius:50%;
                            background:{status_color};{led_animation}"></div>
            </div>
            <div style="margin-top:10px;">
                <div style="display:flex;justify-content:space-between;">
                    <span style="color:#94A3B8;font-size:12px;">{status_text}</span>
                    <span style="color:#fff;font-size:12px;font-weight:600;">
                        {fill:.0f}% fill
                    </span>
                </div>
                <div style="height:8px;background:#334155;border-radius:4px;
                            overflow:hidden;margin-top:4px;">
                    <div style="height:100%;width:{fill}%;
                                background:linear-gradient(90deg,#3B82F6,#10B981);
                                border-radius:4px;transition:width 0.6s;"></div>
                </div>
            </div>
            {f"<div style='color:#94A3B8;font-size:11px;margin-top:8px;'>Fleet #{fleet.id} • {fleet.truck_name or ''}</div>" if fleet else f"<div style='color:#64748b;font-size:11px;margin-top:8px;'>{dock.stage.value}</div>"}
        </div>
    """, unsafe_allow_html=True)

    btn_label = f"Inspect Dock {dock.dock_number}"
    if fleet:
        if st.button(btn_label, key=f"open_dock_{dock.dock_number}",
                     type="primary", width="stretch"):
            st.session_state.selected_fleet_id = fleet.id
            st.rerun()
    else:
        st.button(btn_label, key=f"open_dock_{dock.dock_number}",
                  type="secondary", width="stretch", disabled=True,
                  help="No fleet at this dock yet")


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
