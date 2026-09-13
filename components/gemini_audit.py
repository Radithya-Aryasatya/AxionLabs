"""
components/gemini_audit.py
===========================
Gemini AI Interpretative Audit Log component.
"""

import streamlit as st
from state.fleet_state import Fleet
from utils.formatters import format_datetime


def render_gemini_audit(fleet: Fleet):
    """Render the Gemini AI audit log section for a fleet."""
    st.subheader("🤖 Gemini AI Interpretative Audit")

    gemini_analysis = fleet.gemini_analysis

    if gemini_analysis:
        _render_current_analysis(gemini_analysis, fleet)
    else:
        st.info(
            "No Gemini analysis has been run for this fleet yet. "
            "Use the 'Run Re-Analysis' control (Manager Action Controls above) "
            "or 'SCAN ALL DOCKS' to trigger a spatial review."
        )
    st.markdown("---")
    _render_audit_history(fleet)


def _render_current_analysis(analysis: dict, fleet: Fleet):
    """Render the current Gemini analysis result."""
    _render_provenance(analysis)

    # A FAILED request produced no real analysis — never dress up defaults
    # (or any fallback data) as if they were the model's findings.
    if analysis.get('status') == 'FAILED':
        st.warning(
            "No Gemini analysis to display — the request failed. "
            "Press 'Run Re-Analysis' (Manager Action Controls above) or "
            "'SCAN ALL DOCKS' to retry."
        )
        return

    anomaly_type = analysis.get('anomaly_type', 'UNKNOWN')
    severity = analysis.get('severity', 'NONE')
    paragraph = analysis.get('analysis_paragraph', '')
    recommendations = analysis.get('recommended_actions', [])
    extra = analysis.get('extra', {})

    severity_color = {
        'WARNING': '#F59E0B', 'CRITICAL': '#EF4444', 'NONE': '#10B981'
    }.get(severity, '#6B728B')
    severity_emoji = {
        'WARNING': '⚠️', 'CRITICAL': '🚨', 'NONE': '✅'
    }.get(severity, '❓')

    st.markdown(f"""
        <div style="background: #1e293b; border-radius: 12px; padding: 20px; margin: 12px 0; border-left: 4px solid {severity_color};">
            <div style="display: flex; align-items: center; gap: 12px;">
                <div style="font-size: 24px;">{severity_emoji}</div>
                <div>
                    <div style="font-weight: 700; color: #ffffff; font-size: 14px;">
                        Anomaly Type: {anomaly_type}
                    </div>
                    <div style="font-size: 12px; color: #94A3B8;">
                        Severity: <span style="color: {severity_color}; font-weight: 600;">{severity}</span>
                    </div>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # Pure Gemini narrative — rendered verbatim, no code-box wrapping
    if paragraph:
        st.markdown("#### Analysis Narrative")
        st.markdown(paragraph)

    # Render any additional fields Gemini returned (not restricted to our schema)
    if extra:
        st.markdown("#### Raw Gemini Observations")
        for key, val in extra.items():
            label = key.replace("_", " ").title()
            if isinstance(val, str):
                st.markdown(f"**{label}:** {val}")
            else:
                st.markdown(f"**{label}:** {val}")

    if recommendations:
        st.markdown("#### Recommended Actions")
        for rec in recommendations:
            st.markdown(f"- {rec}")


def _render_provenance(analysis: dict):
    """
    Render the provenance panel: Gemini status, model used and the EXACT raw
    model response. This makes it impossible to mistake simulated, cached or
    failed output for a live Gemini result.
    """
    status = analysis.get('status', '') or 'UNVERIFIED'
    model = analysis.get('model', '') or 'unknown'
    raw = analysis.get('raw_response', '') or ''
    error = analysis.get('error', '') or ''
    provenance = analysis.get('extra', {}).get('provenance', '')

    status_styles = {
        'SUCCESS': ('#10B981', '✅ GEMINI STATUS: SUCCESS — real model response received'),
        'FAILED': ('#EF4444', '❌ GEMINI STATUS: FAILED — the request did NOT succeed'),
        'SIMULATED': ('#3B82F6', '🧪 GEMINI STATUS: SIMULATED — deterministic local rules, NOT live Gemini'),
        'UNVERIFIED': ('#F59E0B', '❓ GEMINI STATUS: UNVERIFIED — legacy result without provenance data'),
    }
    color, label = status_styles.get(status, ('#F59E0B', f'❓ GEMINI STATUS: {status}'))

    st.markdown(f"""
        <div style="background:#0f172a; border-radius:12px; padding:14px; margin:8px 0;
                    border:1px solid {color};">
            <div style="font-weight:700; color:{color}; font-size:13px;">{label}</div>
            <div style="color:#94A3B8; font-size:12px; margin-top:4px;">
                MODEL USED: <code style="color:#E2E8F0;">{model}</code>
            </div>
        </div>
    """, unsafe_allow_html=True)

    if provenance:
        st.caption(f"Provenance: {provenance}")

    if error:
        st.error(f"**Gemini request error ({model}):** {error}")
        st.caption(
            "The raw response is intentionally empty — no real Gemini "
            "content exists for this failed request, and no simulated "
            "substitute was generated."
        )

    st.markdown("##### 📟 RAW GEMINI RESPONSE")
    if raw:
        st.caption(
            f"Exact text returned by Gemini ({len(raw)} characters), "
            "shown verbatim — may be prose or JSON."
        )
        st.code(raw, language=None, line_numbers=False)
    elif status == 'FAILED':
        st.caption("— empty — (no real Gemini response exists for a failed request)")
    elif status == 'SIMULATED':
        st.caption("— empty — (simulated results never carry a Gemini response)")


def _render_audit_history(fleet: Fleet):
    """Render the historical audit log."""
    st.markdown("#### Audit History")

    if not fleet.anomaly_history:
        st.caption("No historical anomalies recorded.")
        return

    for record in reversed(fleet.anomaly_history):
        status_icon = "🔴" if record.severity == "CRITICAL" else "🟡"
        resolved_icon = "✅" if record.resolved else "🔴"

        with st.expander(
            f"{status_icon} {record.anomaly_type} — {record.severity} "
            f"({format_datetime(record.timestamp)})"
        ):
            st.markdown(f"**Severity:** {record.severity}")
            st.markdown(f"**Resolved:** {resolved_icon}")
            st.markdown(f"**Analysis:**\n\n{record.analysis_paragraph}")

            if record.recommended_actions:
                st.markdown("**Recommended Actions:**")
                for rec in record.recommended_actions:
                    st.markdown(f"- {rec}")


# NOTE: the former "Run Gemini Spatial Analysis" button and its
# _run_analysis() helper were removed. Per-fleet Gemini re-analysis
# now happens exclusively through the manager "Run Re-Analysis"
# control (components/manager_controls.py), which sends BOTH the CCTV
# image and the virtual digital-twin render to the Gemini API.
