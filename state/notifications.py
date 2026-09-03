"""
state/notifications.py
======================
Cross-view notification store for the Executive Fleet Diagnostic Center.

A single source of truth for alert notifications. The header bell badge,
the dock-card LEDs, and the @st.dialog Alert Feed all derive from this
store so that a worker-triggered anomaly in View 1 surfaces instantly
in View 2 (and vice-versa).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

# Notification severity levels (ordered for color mapping)
LEVELS = ("INFO", "RESOLVED", "WARNING", "CRITICAL")

LEVEL_COLOR = {
    "INFO": "#3B82F6",
    "RESOLVED": "#10B981",
    "WARNING": "#F59E0B",
    "CRITICAL": "#EF4444",
}

LEVEL_EMOJI = {
    "INFO": "ℹ️",
    "RESOLVED": "✅",
    "WARNING": "⚠️",
    "CRITICAL": "🚨",
}


@dataclass
class FleetNotification:
    """A single alert event surfaced to the manager."""
    dock_number: int
    fleet_id: str
    level: str                  # one of LEVELS
    title: str
    body: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    created_at: datetime = field(default_factory=datetime.now)
    read: bool = False


# --- STORE HELPERS (operate on st.session_state['notifications']) ---

def _ensure_store():
    import streamlit as st
    if 'notifications' not in st.session_state:
        st.session_state.notifications = []


def push_notification(dock_number: int, fleet_id: str, level: str,
                       title: str, body: str = "") -> FleetNotification:
    """Append a notification and return it."""
    import streamlit as st
    _ensure_store()
    n = FleetNotification(
        dock_number=dock_number,
        fleet_id=fleet_id,
        level=level,
        title=title,
        body=body,
    )
    st.session_state.notifications.append(n)
    return n


def all_notifications() -> List[FleetNotification]:
    """Return all notifications, newest first."""
    import streamlit as st
    _ensure_store()
    return list(reversed(st.session_state.notifications))


def unread_notifications() -> List[FleetNotification]:
    """Return unread notifications, newest first."""
    return [n for n in all_notifications() if not n.read]


def unread_count() -> int:
    """Number of unread notifications (drives the bell badge)."""
    return len(unread_notifications())


def mark_all_read():
    """Mark every notification as read."""
    import streamlit as st
    _ensure_store()
    for n in st.session_state.notifications:
        n.read = True


def mark_read(notification_id: str):
    """Mark a single notification as read by id."""
    import streamlit as st
    _ensure_store()
    for n in st.session_state.notifications:
        if n.id == notification_id:
            n.read = True
            break


def clear_all():
    """Wipe the notification store (used by demo reset)."""
    import streamlit as st
    st.session_state.notifications = []
