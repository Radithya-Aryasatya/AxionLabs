"""
components/tri_view_panel.py
=============================
Fleet Detail Inspection View (Tri-View Panel).

When a manager selects a fleet, this panel displays 3 things:
  1. CCTV Live Stream & Depth View (with RGB/Depth toggle)
  2. Digital Twin (3D Bin Packing Plan)
  3. Cargo Manifest & Gemini AI Interpretative Audit Log
"""

import streamlit as st
from state.fleet_state import (
    Fleet, FleetStatus, select_fleet, resolve_anomaly,
    AnomalyRecord, add_anomaly_record,
)
from services.anomaly_engine import AnomalyEngine
from components.cctv_feed import render_cctv_feed
from components.digital_twin import render_digital_twin
from components.cargo_manifest_panel import render_cargo_manifest
from components.gemini_audit import render_gemini_audit
from components.manager_controls import render_manager_controls
from datetime import datetime


def render_tri_view_panel(fleet: Fleet):
    """
    Render the full Tri-View Detail Inspection panel for a fleet.
    Uses a 3-column layout for the main panels.
    """
    # --- Return button ---
    st.markdown("---")
    if st.button("← Back to Fleet Overview", key=f"back_{fleet.id}", type="secondary"):
        select_fleet(None)
        # Rerun immediately so the overview grid renders this interaction
        st.rerun()
        
    # --- Panel Header with Fleet Info ---
    _render_panel_header(fleet)

    # --- Manager Action Controls (Resolve / Override / Re-analyze) ---
    render_manager_controls(fleet)

    st.markdown("---")

    # --- Three-Panel Layout ---
    # Panel 1: CCTV Feed | Panel 2: Digital Twin
    col_left, col_center = st.columns([1, 1])

    with col_left:
        st.markdown("### 1️⃣ CCTV Live Stream & Depth View")
        render_cctv_feed(
            dock_number=fleet.dock_number,
            cctv_frame_path=fleet.cctv_frame_path,
            depth_map_path=fleet.depth_map_path,
        )

    with col_center:
        st.markdown("### 2️⃣ Digital Twin (3D Bin Packing Plan)")
        render_digital_twin(fleet)

    # Panel 3: Cargo Manifest + Gemini Audit (full width)
    st.markdown("---")
    st.markdown("### 3️⃣ Cargo Manifest & Gemini AI Audit")

    col_right1, col_right2 = st.columns([1, 1])

    with col_right1:
        render_cargo_manifest(fleet)

    with col_right2:
        render_gemini_audit(fleet)

    


def _render_panel_header(fleet: Fleet):
    """Render the header section of the tri-view panel."""
    status_emoji = {
        FleetStatus.LOADING: "🔵",
        FleetStatus.INSPECTED_CLEAR: "✅",
        FleetStatus.ANOMALY_DETECTED: "⚠️",
        FleetStatus.BLOCKED: "🚨",
    }.get(fleet.status, "⚪")

    header_html = f"""
    <div style="
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border-radius: 12px;
        padding: 16px 24px;
        margin-bottom: 16px;
        border: 1px solid #334159;
    ">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <h1 style="margin: 0; color: #ffffff; font-size: 22px;">
                    {status_emoji} Fleet #{fleet.id} — Dock {fleet.dock_number}
                </h1>
                <p style="margin: 4px 0; color: #94A3B8; font-size: 13px;">
                    Truck: {fleet.truck_name or f"Truck-{fleet.id}"} |
                    Dimensions: {fleet.truck_dimensions[0]} × {fleet.truck_dimensions[1]} × {fleet.truck_dimensions[2]} m
                </p>
            </div>
            <div style="
                background: {fleet.status.color};
                color: white;
                padding: 6px 14px;
                border-radius: 20px;
                font-weight: 700;
                font-size: 12px;
            ">
                {fleet.status.value}
            </div>
        </div>
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)
