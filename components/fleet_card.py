"""
components/fleet_card.py
=========================
Fleet Card component for the Executive Control Tower overview grid.

Each card displays:
  - Truck ID & Dock Number (e.g., "Fleet #TK-04 | Dock 02")
  - Live Status Badge with color coding
  - Quick Progress Bar (volumetric fill percentage)
  - Click → opens Fleet Detail Inspection View (Tri-View Panel)
"""

import streamlit as st
from state.fleet_state import Fleet, FleetStatus
from utils.formatters import status_emoji, get_fill_color, render_colored_progress
from datetime import datetime


def render_fleet_card(
    fleet: Fleet,
    on_click_callback=None,
    is_selected: bool = False,
):
    """
    Render a single fleet card in the overview grid.

    Parameters
    ----------
    fleet : Fleet
        The fleet data model to display.
    on_click_callback : callable or None
        Callback invoked when the card is clicked. Passes the fleet.
    is_selected : bool
        Whether this fleet is currently selected (for highlighting).
    """
    status = fleet.status
    status_color = status.color
    status_text = status.value
    emoji = status_emoji(status)

    # Card container with border highlighting if selected
    border_style = f"2px solid {status_color}" if is_selected else "1px solid #334159"

    # Use st.markdown for the full card with custom styling
    card_html = f"""
    <div id="fleet-card-{fleet.id}" style="
        border: {border_style};
        border-radius: 12px;
        padding: 16px;
        margin: 8px;
        background: linear-gradient(145deg, #1e293b 0%, #334159 100%);
        cursor: pointer;
        transition: transform 0.1s, box-shadow 0.1s;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    ">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <div>
                <h3 style="margin: 0; color: #ffffff; font-size: 16px;">
                    Fleet #{fleet.id}
                </h3>
                <p style="margin: 4px 0; color: #94A3B8; font-size: 12px;">
                    Dock {fleet.dock_number}
                </p>
            </div>
            <div style="
                background: {status_color};
                color: white;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 11px;
                font-weight: 700;
                display: flex;
                align-items: center;
                gap: 4px;
            ">
                {emoji} {status_text}
            </div>
        </div>

        <div style="margin: 12px 0;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                <span style="color: #94A3B8; font-size: 12px;">Fill Rate</span>
                <span style="color: #ffffff; font-size: 12px; font-weight: 600;">
                    {fleet.fill_percentage:.1f}%
                </span>
            </div>
            <div style="
                height: 8px;
                background: #475569;
                border-radius: 4px;
                overflow: hidden;
            ">
                <div style="
                    height: 100%;
                    background: linear-gradient(90deg, {get_fill_color(fleet.fill_percentage)} 0%, #059669 100%);
                    width: {fleet.fill_percentage}%;
                    transition: width 0.3s ease;
                "></div>
            </div>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 12px;">
            <span style="color: #64748b; font-size: 11px;">
                Updated: {fleet.last_updated.strftime('%H:%M:%S')}
            </span>
            <span style="color: #64748b; font-size: 11px;">
                Items: {fleet.packing_layout.get('packed_count', 0)} packed
            </span>
        </div>
    </div>
    """

    st.markdown(card_html, unsafe_allow_html=True)

    # Click handler — invisible button overlay
    btn_key = f"select_fleet_{fleet.id}"
    if st.button("Select Fleet", key=btn_key, type="primary", width='stretch'):
        if on_click_callback:
            on_click_callback(fleet)


def render_fleet_card_compact(fleet: Fleet) -> bool:
    """
    Render a compact fleet card using Streamlit native widgets.
    Returns True if the card was clicked.

    This version uses st.container and st.button for better mobile
    responsiveness and avoids custom HTML.
    """
    status = fleet.status
    emoji = status_emoji(status)

    with st.container(border=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"### Fleet #{fleet.id} | Dock {fleet.dock_number}")
            st.caption(f"{emoji} {status.value}")
        with col2:
            st.markdown(f"**{fleet.fill_percentage:.0f}%**")
            render_colored_progress(fleet.fill_percentage)

    clicked = st.button(
        "Open Detail View",
        key=f"open_detail_{fleet.id}",
        type="primary",
        width='stretch',
    )
    if clicked:
        st.session_state.selected_fleet_id = fleet.id
        # Rerun immediately so the tri-view panel renders this interaction
        # (the selection branch in the dashboard was already passed).
        st.rerun()

    return clicked
