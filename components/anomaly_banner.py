"""
components/anomaly_banner.py
==============================
Alert banner components for anomaly notifications.

  - WARNING banner: Yellow/orange for any detected anomaly (Scenarios 1 & 2)
"""

import streamlit as st


def render_anomaly_banners():
    """
    Render all active anomaly banners for fleets in View 2.
    Scans active_fleets for any with unresolved anomalies or blocked status.
    """
    import streamlit as st
    from state.fleet_state import get_fleet_by_id

    if 'active_fleets' not in st.session_state:
        return

    fleets = st.session_state.get('active_fleets', [])
    banners_rendered = 0

    for fleet in fleets:
        # Check for unresolved anomalies
        unresolved = [
            a for a in fleet.anomaly_history
            if not a.resolved
        ]

        # Render the yellow warning banner for any fleet with an unresolved
        # anomaly, regardless of whether it also reached BLOCKED FROM DEPARTURE.
        if fleet.status.value in ("BLOCKED FROM DEPARTURE", "ANOMALY DETECTED"):
            latest = unresolved[-1] if unresolved else None
            analysis_text = latest.analysis_paragraph if latest else "Anomaly detected."
            render_warning_banner(
                fleet_id=fleet.id,
                dock_number=fleet.dock_number,
                analysis_text=analysis_text,
            )
            banners_rendered += 1


def render_warning_banner(fleet_id: str, dock_number: int, analysis_text: str = ""):
    """
    Render a yellow/orange warning banner.
    Triggered by Scenario 1: Messy/Unstable Stacking.
    """
    if 'rendered_warnings' not in st.session_state:
        st.session_state.rendered_warnings = []

    banner_key = f"warning_{fleet_id}_{dock_number}"
    if banner_key in st.session_state.rendered_warnings:
        return  # Don't re-render

    st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, #F59E0B 0%, #D97706 100%);
            border-radius: 12px;
            padding: 16px 20px;
            margin: 12px 0;
            border: 2px solid #D97706;
            animation: pulse 2s infinite;
            color: #000;
        ">
            <div style="display: flex; align-items: center; gap: 12px;">
                <div style="font-size: 24px;">⚠️</div>
                <div>
                    <div style="font-weight: 700; font-size: 14px; margin-bottom: 4px;">
                        ANOMALY DETECTED: at Dock {dock_number}
                    </div>
                    <div style="font-size: 12px; opacity: 0.9;">
                        Fleet #{fleet_id}
                    </div>
                </div>
            </div>
        </div>
        <style>
        @keyframes pulse {{
            0% {{ box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.4); }}
            70% {{ box-shadow: 0 0 0 10px rgba(245, 158, 11, 0); }}
            100% {{ box-shadow: 0 0 0 0 rgba(245, 158, 11, 0); }}
        }}
        </style>
    """, unsafe_allow_html=True)

    st.session_state.rendered_warnings.append(banner_key)


def clear_banners_for_fleet(fleet_id: str):
    """Remove rendered banner markers for a fleet (so they can re-render)."""
    import streamlit as st
    if 'rendered_warnings' in st.session_state:
        st.session_state.rendered_warnings = [
            k for k in st.session_state.rendered_warnings
            if not k.startswith(f"warning_{fleet_id}")
        ]
