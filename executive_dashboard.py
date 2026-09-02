"""
executive_dashboard.py
=======================
Executive Control Tower — Main View 2 controller.

Landing view for the Manager role. Displays:
  - Persistent anomaly alert banners (all active fleets)
  - Fleet Overview Grid of Fleet Cards
  - Tri-View Detail Inspection Panel (when a fleet is selected)

Note: This file is named with underscore (executive_dashboard.py) so it can
be imported as a Python module. The original executive-dashboard.py (with
hyphen) has been superseded by this version.
"""

import streamlit as st
from state.fleet_state import Fleet, FleetStatus, get_fleet_by_id, select_fleet
from components.fleet_card import render_fleet_card_compact
from components.anomaly_banner import render_anomaly_banners
from components.tri_view_panel import render_tri_view_panel


def render_executive_dashboard():
    """
    Main entry point for the Executive Control Tower view.
    Call this from app.py when view_mode == 'executive'.
    """
    # Page header
    st.markdown("""
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 20px;">
            <div style="font-size: 32px;">🛰️</div>
            <div>
                <h1 style="margin: 0; color: #ffffff;">Executive Control Tower</h1>
                <p style="margin: 4px 0; color: #94A3B8; font-size: 13px;">
                    Fleet Monitoring & Diagnostic Dashboard
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

    # --- Fleet Status Summary ---
    _render_status_summary(fleets)

    st.markdown("---")

    # --- Tri-View Detail Panel (if a fleet is selected) ---
    selected_id = st.session_state.get('selected_fleet_id')
    selected_fleet = get_fleet_by_id(selected_id) if selected_id else None

    if selected_fleet:
        render_tri_view_panel(selected_fleet)
    else:
        # --- Fleet Overview Grid ---
        _render_fleet_grid(fleets)


def _render_fleet_grid(fleets):
    """Render the fleet overview grid of cards."""
    st.markdown("### 🚛 Active Fleets at Loading Docks")
    st.caption(f"{len(fleets)} fleet(s) currently at docks")

    for fleet in fleets:
        render_fleet_card_compact(fleet)


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
