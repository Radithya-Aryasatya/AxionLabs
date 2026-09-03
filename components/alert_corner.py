"""
components/alert_corner.py
===========================
In-dashboard notification center for the Executive Control Tower.

Instead of a global header bell, anomaly alerts appear as a FIXED corner
stack in the top-right of the executive dashboard — a projector-friendly
"control room" look with severity-colored cards (CRITICAL red pulse,
WARNING amber, RESOLVED green, INFO blue).

Actions use st.query_params links (no DOM hacks): "Inspect ->" selects the
fleet, "X" dismisses, "Mark all read" clears the stack. The dashboard reads
the params on rerun, acts, then clears them.
"""

import streamlit as st
from datetime import datetime

from state.notifications import (
    all_notifications, unread_count, mark_all_read, mark_read,
    LEVEL_COLOR, LEVEL_EMOJI,
)
from state.dock_state import set_dock_alert, get_dock_state

# Fixed-position corner styling (injected once)
_CORNER_CSS = """
<style>
@keyframes alert-slidein {
  from { opacity: 0; transform: translateX(40px); }
  to   { opacity: 1; transform: translateX(0); }
}
@keyframes alert-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.5); }
  50%      { box-shadow: 0 0 0 8px rgba(239, 68, 68, 0); }
}
.axion-alert-stack {
  position: fixed; top: 76px; right: 16px; width: 320px; z-index: 1001;
  display: flex; flex-direction: column; gap: 10px; max-height: 70vh;
  overflow-y: auto;
}
.axion-alert-card {
  border-radius: 10px; padding: 12px 14px; color: #fff;
  border-left: 5px solid #fff5;
  animation: alert-slidein 0.35s ease-out;
}
.axion-alert-card.critical { animation: alert-slidein 0.35s ease-out, alert-pulse 2s infinite; }
.axion-alert-card .a-title { font-weight: 700; font-size: 13px; }
.axion-alert-card .a-body  { font-size: 11.5px; opacity: 0.92; margin-top: 2px; }
.axion-alert-card .a-meta  { font-size: 10px; opacity: 0.7; margin-top: 4px; }
.axion-alert-markall {
  font-size: 11px; text-align: right; margin-bottom: 4px;
}
</style>
"""


def _handle_alert_actions():
    """Read query-param actions, act, then clear params. Called once per rerun."""
    params = st.query_params
    action = params.get("exec_act", None)

    if action == "inspect":
        dock = params.get("exec_dock", None)
        if dock is not None:
            try:
                dock_num = int(dock)
            except ValueError:
                dock_num = None
            dock_state = get_dock_state(dock_num) if dock_num else None
            if dock_state and dock_state.fleet_id:
                st.session_state["selected_fleet_id"] = dock_state.fleet_id
            set_dock_alert(dock_num, False)
            mark_all_read()
        st.query_params.clear()
        st.rerun()

    elif action == "dismiss":
        nid = params.get("exec_nid", None)
        if nid:
            mark_read(nid)
        st.query_params.clear()
        st.rerun()

    elif action == "markall":
        mark_all_read()
        from state.dock_state import get_all_docks
        for d in get_all_docks().values():
            set_dock_alert(d.dock_number, False)
        st.query_params.clear()
        st.rerun()


def render_alert_corner():
    """Render the fixed top-right alert stack. Call inside the executive view."""
    _handle_alert_actions()

    notifications = all_notifications()
    count = unread_count()

    st.markdown(_CORNER_CSS, unsafe_allow_html=True)

    # Build the stack as a single HTML block (visual only; actions are links).
    html_parts = ['<div class="axion-alert-stack">']

    if count:
        html_parts.append(
            '<div class="axion-alert-markall">'
            '<a href="?exec_act=markall" style="color:#93C5FD;text-decoration:none;">'
            'Mark all read (%d)</a></div>' % count
        )

    if not notifications:
        html_parts.append(
            '<div style="position:fixed;top:76px;right:16px;z-index:1001;'
            'background:#1e293b;border:1px solid #334159;border-radius:10px;'
            'padding:12px 16px;color:#94A3B8;font-size:12px;width:240px;">'
            '🔔 No active alerts — all docks operating normally.</div>'
        )
    else:
        for n in notifications:
            color = LEVEL_COLOR.get(n.level, "#6B7280")
            dot = LEVEL_EMOJI.get(n.level, "•")
            css_class = "axion-alert-card " + n.level.lower()
            read_style = "" if not n.read else "opacity:0.5;"
            ago = ""
            delta = (datetime.now() - n.created_at).total_seconds()
            ago = "%ds ago" % int(delta) if delta < 120 else n.created_at.strftime("%H:%M:%S")

            # Action links
            inspect_link = '<a href="?exec_act=inspect&exec_dock=%d" style="color:#fff;font-weight:700;text-decoration:none;">Inspect →</a>' % n.dock_number
            dismiss_link = '<a href="?exec_act=dismiss&exec_nid=%s" style="color:#fff;opacity:0.7;text-decoration:none;font-size:14px;">✕</a>' % n.id

            html_parts.append('''
<div class="%s" style="background:%s;%s">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
    <div style="flex:1;">
      <div class="a-title">%s %s</div>
      <div class="a-body">%s</div>
      <div class="a-meta">Dock %d · %s %s</div>
    </div>
    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px;">
      %s %s
    </div>
  </div>
</div>''' % (css_class, color, read_style, dot, n.title, (n.body or "")[:120],
              n.dock_number, ago, "· unread" if not n.read else "",
              inspect_link, dismiss_link))

    html_parts.append('</div>')
    st.markdown("\n".join(html_parts), unsafe_allow_html=True)
