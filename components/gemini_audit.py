"""
components/gemini_audit.py
===========================
Gemini AI Interpretative Audit Log component.
"""

import streamlit as st
from datetime import datetime
from state.fleet_state import Fleet, AnomalyRecord, add_anomaly_record
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
            "Click 'Run Analysis' below to trigger a spatial review."
        )

    if st.button("🔍 Run Gemini Spatial Analysis", key=f"run_analysis_{fleet.id}", type="primary"):
        _run_analysis(fleet)

    st.markdown("---")
    _render_audit_history(fleet)


def _render_current_analysis(analysis: dict, fleet: Fleet):
    """Render the current Gemini analysis result."""
    anomaly_type = analysis.get('anomaly_type', 'UNKNOWN')
    severity = analysis.get('severity', 'NONE')
    confidence = analysis.get('confidence', 0.0)
    paragraph = analysis.get('analysis_paragraph', '')
    affected = analysis.get('affected_items', [])
    recommendations = analysis.get('recommended_actions', [])
    discrepancy = analysis.get('spatial_discrepancy_score', 0.0)

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
                        Severity: <span style="color: {severity_color}; font-weight: 600;">{severity}</span> |
                        Confidence: {confidence * 100:.1f}% |
                        Discrepancy: {discrepancy:.3f}
                    </div>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("#### Analysis Narrative")
    st.markdown(f'```\n{paragraph}\n```')

    if affected:
        st.markdown("#### Affected Items")
        for item in affected:
            st.markdown(f"- `{item}`")

    if recommendations:
        st.markdown("#### Recommended Actions")
        for rec in recommendations:
            st.markdown(f"- {rec}")


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

            if record.affected_items:
                st.markdown("**Affected Items:**")
                for item in record.affected_items:
                    st.markdown(f"- {item}")

            if record.recommended_actions:
                st.markdown("**Recommended Actions:**")
                for rec in record.recommended_actions:
                    st.markdown(f"- {rec}")


def _run_analysis(fleet: Fleet):
    """Trigger Gemini analysis for a fleet (called from button)."""
    from services.anomaly_engine import AnomalyEngine

    engine = AnomalyEngine()
    decision = engine.run_full_analysis(fleet)

    # Capture the structured Gemini result stashed by the engine
    result = getattr(engine, 'last_result', None)
    if result is not None:
        fleet.gemini_analysis = result.to_dict()

    # Apply the engine decision to the fleet status
    fleet.status = decision.fleet_status

    # Add anomaly record if applicable
    if decision.severity in ("WARNING", "CRITICAL"):
        record = AnomalyRecord(
            anomaly_type=decision.anomaly_type,
            severity=decision.severity,
            timestamp=datetime.now(),
            analysis_paragraph=(
                result.analysis_paragraph if result else decision.banner_message
            ),
            affected_items=result.affected_items if result else [],
            recommended_actions=result.recommended_actions if result else [],
        )
        add_anomaly_record(fleet, record)

    st.rerun()
