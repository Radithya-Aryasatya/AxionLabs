"""
components/alert_corner.py
===========================
In-dashboard notification center for the Executive Control Tower.

Anomaly alerts appear as a FIXED corner stack in the top-right of the
executive dashboard — a projector-friendly "control room" look with
severity-colored cards (CRITICAL red pulse, WARNING amber, RESOLVED green,
INFO blue).

There is a SINGLE action button — "Mark all read (n)" — which closes the
entire notification stack. The cards themselves are visual-only (no per-
card Inspect / dismiss buttons) so the layout is dead simple.

Layout strategy (no ancestor squeezing):
  - The visual cards are a single HTML block rendered position:fixed at the
    top-right — this never touches the dashboard's flow layout.
  - The "Mark all read" button is a native st.button, but it lives in the
    normal document flow. A hidden marker div is rendered directly before it,
    and the CSS adjacent-sibling rule (`#axion-markall-marker + *`) pins ONLY
    that button's own wrapper fixed in the corner. The `+` combinator can
    never match an ancestor, so the dashboard can never get squeezed.
"""

import streamlit as st
from datetime import datetime

from state.notifications import (
    all_notifications, unread_count, clear_all, LEVEL_COLOR, LEVEL_EMOJI,
)
from state.dock_state import clear_all_dock_alerts

# Fixed-position corner styling (injected once).
#
# KEY: we never style any ancestor container. The cards below are a single
# position:fixed HTML block (classic "corner toast" pattern). The button is
# pinned by the adjacent-sibling rule that follows the hidden marker — the
# `+` combinator matches ONLY the element immediately after the marker (the
# button's own wrapper), so no parent block can ever be targeted.
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
#axion-markall-marker { display: none; }
#axion-markall-marker + * {
  position: fixed; top: 76px; right: 16px; width: 336px; z-index: 1001;
}
#axion-markall-marker + * button { width: 100%; }
.axion-alert-stack {
  position: fixed; right: 16px; width: 336px; z-index: 1000;
  display: flex; flex-direction: column; gap: 10px; max-height: 70vh;
  overflow-y: auto;
}
.axion-alert-card {
  border-radius: 10px; padding: 12px 14px; color: #fff;
  border-left: 5px solid #fff5;
  animation: alert-slidein 0.35s ease-out;
}
.axion-alert-card.critical {
  animation: alert-slidein 0.35s ease-out, alert-pulse 2s infinite;
}
.axion-alert-card .a-title { font-weight: 700; font-size: 13px; }
.axion-alert-card .a-body  { font-size: 11.5px; opacity: 0.92; margin-top: 2px; }
.axion-alert-card .a-meta  { font-size: 10px; opacity: 0.7; margin-top: 4px; }
</style>
"""


def render_alert_corner():
    """Render the fixed top-right alert stack. Call inside the executive view."""
    st.markdown(_CORNER_CSS, unsafe_allow_html=True)

    notifications = all_notifications()
    unread = unread_count()

    # The single action button. It lives in normal flow; the hidden marker
    # directly before it lets the CSS adjacent-sibling rule pin just this
    # button's wrapper to the top-right corner (no ancestor is ever styled).
    if unread:
        st.markdown('<div id="axion-markall-marker"></div>', unsafe_allow_html=True)
        if st.button(
            "Mark all read (%d)" % unread,
            key="axion_alert_markall",
            help="Close every notification in the stack",
        ):
            clear_all()
            clear_all_dock_alerts()
            st.rerun()

    # Visual-only card stack. position:fixed so it never affects page flow.
    # When the button is present, push the stack below it (~116px); otherwise
    # sit it at the very top (76px).
    stack_top = 116 if unread else 76
    html_parts = ['<div class="axion-alert-stack" style="top:%dpx;">' % stack_top]

    if not notifications:
        html_parts.append(
            '<div class="axion-alert-card" style="background:#1e293b;'
            'border:1px solid #334159;">'
            '<div class="a-body" style="color:#94A3B8;font-size:12px;">'
            '🔔 No active alerts — all docks operating normally.</div></div>'
        )
    else:
        for n in notifications:
            color = LEVEL_COLOR.get(n.level, "#6B7280")
            dot = LEVEL_EMOJI.get(n.level, "•")
            css_class = "axion-alert-card " + n.level.lower()
            body_text = (n.body or "")[:120]
            delta = (datetime.now() - n.created_at).total_seconds()
            ago = "%ds ago" % int(delta) if delta < 120 else n.created_at.strftime("%H:%M:%S")
            unread_tag = " · unread" if not n.read else ""

            html_parts.append(
                '<div class="%s" style="background:%s;">'
                '  <div style="display:flex;justify-content:space-between;'
                '              align-items:flex-start;gap:8px;">'
                '    <div style="flex:1;">'
                '      <div class="a-title">%s %s</div>'
                '      <div class="a-body">%s</div>'
                '      <div class="a-meta">Dock %d · %s%s</div>'
                '    </div>'
                '  </div>'
                '</div>' % (css_class, color, dot, n.title, body_text,
                            n.dock_number, ago, unread_tag)
            )

    html_parts.append('</div>')
    st.markdown("\n".join(html_parts), unsafe_allow_html=True)

