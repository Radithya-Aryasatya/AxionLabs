"""
components/status_ticker.py
===========================
Control-room status ticker using a self-refreshing @st.fragment.

Shows a ticking facility clock, a blinking LIVE dot, per-dock "last sync"
timestamps, and the current analysis source — all inside a fragment that
reruns every few seconds so the main page never needs to rerun.
"""

import streamlit as st
from datetime import datetime
from state.dock_state import get_all_docks, DockStage, AnalysisSource


def _stage_emoji(stage: DockStage) -> str:
    return {
        DockStage.AWAITING_RENDER: "⏳",
        DockStage.LOADING: "🔵",
        DockStage.ANALYZING: "🛰️",
        DockStage.MONITORED: "🟢",
    }.get(stage, "⚪")


def _source_chip(source: AnalysisSource) -> str:
    color = {
        AnalysisSource.NONE: "#6B7280",
        AnalysisSource.LIVE_GEMINI: "#10B981",
        AnalysisSource.FALLBACK_CACHED: "#F59E0B",
        AnalysisSource.FALLBACK_SIMULATED: "#3B82F6",
    }.get(source, "#6B7280")
    return (f"<span style='background:{color};color:white;padding:2px 8px;"
            f"border-radius:10px;font-size:10px;font-weight:700;'>"
            f"{source.value}</span>")


@st.fragment(run_every=3)
def render_status_ticker():
    """Auto-refreshing control-room ticker bar."""
    now = datetime.now()
    docks = get_all_docks()

    st.markdown("""
        <style>
        @keyframes blink { 0%,100%{opacity:1;} 50%{opacity:0.3;} }
        .live-dot { display:inline-block; width:9px; height:9px; border-radius:50%;
                    background:#10B981; animation:blink 1.5s infinite; }
        </style>
    """, unsafe_allow_html=True)

    parts = [f"<span class='live-dot'></span> <b>LIVE</b>"]
    parts.append(f"<span style='color:#94A3B8;'>{now.strftime('%H:%M:%S')}</span>")

    for dn in sorted(docks):
        dock = docks[dn]
        if dock.fleet_id is None:
            continue
        fleet = dock.fleet()
        ago = ""
        if fleet and fleet.last_updated:
            delta = (now - fleet.last_updated).total_seconds()
            ago = f"{int(delta)}s ago" if delta < 120 else fleet.last_updated.strftime('%H:%M:%S')
        parts.append(
            f"{_stage_emoji(dock.stage)} Dock {dn}"
            f"{' • ' + ago if ago else ''} {_source_chip(dock.analysis_source)}"
        )

    st.markdown(
        f"<div style='font-size:12px;color:#CBD5E1;display:flex;gap:18px;"
        f"align-items:center;flex-wrap:wrap;'>{' &nbsp;|&nbsp; '.join(parts)}</div>",
        unsafe_allow_html=True,
    )
