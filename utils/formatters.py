"""
utils/formatters.py
====================
Helper formatting functions used across the Executive Dashboard.
"""

from datetime import datetime
from typing import Tuple
from state.fleet_state import FleetStatus


def format_status_badge(status: FleetStatus) -> str:
    """Return a human-readable status string for display."""
    return status.value


def render_colored_progress(value_pct: float, color: str = None) -> None:
    """
    Render a colored progress bar via HTML.

    Used instead of st.progress() because the installed Streamlit version
    does not support the `color` kwarg on st.progress().
    """
    import streamlit as st

    pct = max(0.0, min(100.0, float(value_pct)))
    if color is None:
        color = get_fill_color(pct)
    st.markdown(
        f"""
        <div style="
            width: 100%; height: 8px;
            background: #334155;
            border-radius: 4px;
            overflow: hidden;
        ">
            <div style="
                width: {pct:.1f}%; height: 100%;
                background: {color};
                border-radius: 4px;
            "></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def get_status_color(status: FleetStatus) -> str:
    """Return the CSS hex color for a FleetStatus."""
    return status.color


def format_datetime(dt: datetime) -> str:
    """Format a datetime for display in the UI."""
    if dt is None:
        return "—"
    return dt.strftime("%b %d, %Y %H:%M:%S")


def format_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs}s"


def format_volume(volume_cm3: float) -> str:
    """Format a volume in cm³ to a human-readable string."""
    if volume_cm3 >= 1e6:
        return f"{volume_cm3 / 1e6:.1f} m³"
    elif volume_cm3 >= 1e3:
        return f"{volume_cm3 / 1e3:.1f} L"
    return f"{volume_cm3:.0f} cm³"


def get_fill_color(fill_pct: float) -> str:
    """Return a color for the progress bar based on fill percentage."""
    if fill_pct < 30:
        return "#EF4444"  # Red - underfilled
    elif fill_pct < 60:
        return "#F59E0B"  # Amber
    elif fill_pct < 90:
        return "#10B981"  # Green
    return "#059669"  # Dark green - optimal


def truncate_text(text: str, max_len: int = 100) -> str:
    """Truncate text to a maximum length with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def status_emoji(status: FleetStatus) -> str:
    """Return an emoji for the given status."""
    emoji_map = {
        FleetStatus.LOADING: "🔵",
        FleetStatus.INSPECTED_CLEAR: "✅",
        FleetStatus.ANOMALY_DETECTED: "⚠️",
        FleetStatus.BLOCKED: "🚨",
        FleetStatus.PAUSED_AUDIT: "⚠️",
    }
    return emoji_map.get(status, "⚪")
