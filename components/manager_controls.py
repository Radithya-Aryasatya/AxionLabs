"""
components/manager_controls.py
===============================
Manager action strip + @st.dialog override modal for the tri-view panel.

- render_manager_controls(fleet): the always-visible action strip
  (Resolve / Override / Re-analyze / Mark Inspected).
- _override_dialog(fleet): a @st.dialog requiring a reason code before
  clearing a BLOCKED fleet — adds audit-theater for the pitch.
"""

import streamlit as st
from datetime import datetime
from state.fleet_state import Fleet, FleetStatus, resolve_anomaly, AnomalyRecord
from state.dock_state import set_dock_stage, DockStage
from state.notifications import push_notification

OVERRIDE_REASONS = [
    "Re-stacked on site — verified safe",
    "False positive — verified clear by inspector",
    "Supervisor judgment call — risk accepted",
    "Departure cues were a sensor glitch",
]


def _apply_override(fleet: Fleet, reason: str, note: str):
    """Resolve the anomaly, append the reason to the audit trail, notify."""
    resolve_anomaly(fleet)
    fleet.anomaly_history.append(AnomalyRecord(
        anomaly_type="MANAGER_OVERRIDE", severity="NONE",
        timestamp=datetime.now(),
        analysis_paragraph=(
            f"Manager override applied. Reason: {reason}."
            + (f" Note: {note}" if note else "")
        ),
        affected_items=[], recommended_actions=[],
        resolved=True, resolved_at=datetime.now(),
    ))
    set_dock_stage(fleet.dock_number, DockStage.MONITORED)
    push_notification(
        dock_number=fleet.dock_number, fleet_id=fleet.id, level="RESOLVED",
        title=f"Dock {fleet.dock_number} — released by manager override",
        body=reason,
    )
    st.toast(f"🔓 Dock {fleet.dock_number} released — manager override", icon="🔓")
    st.rerun()


def render_manager_controls(fleet: Fleet):
    """Render the manager action strip for a fleet. Returns nothing."""
    st.markdown("### 🛠 Manager Action Controls")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if fleet.status == FleetStatus.ANOMALY_DETECTED:
            if st.button("✅ Resolve Anomaly", key=f"resolve_{fleet.id}",
                         type="secondary", width="stretch"):
                resolve_anomaly(fleet)
                set_dock_stage(fleet.dock_number, DockStage.MONITORED)
                push_notification(
                    dock_number=fleet.dock_number, fleet_id=fleet.id,
                    level="RESOLVED",
                    title=f"Dock {fleet.dock_number} — anomaly resolved",
                    body="Marked resolved by manager.",
                )
                st.toast(f"✅ Dock {fleet.dock_number} anomaly resolved",
                         icon="✅")
                st.rerun()

    with col2:
        if fleet.status == FleetStatus.BLOCKED:
            if st.button("🔓 Manager Override", key=f"override_{fleet.id}",
                         type="primary", width="stretch"):
                # Toggle an inline reason-code confirmation form
                st.session_state["override_open_" + fleet.id] = True
                st.rerun()
            # Inline confirmation form (renders right below the button)
            if st.session_state.get("override_open_" + fleet.id):
                st.markdown("**Select override reason:**")
                reason = st.selectbox("Reason code", OVERRIDE_REASONS,
                                      key=f"override_reason_{fleet.id}")
                note = st.text_area("Optional note",
                                    key=f"override_note_{fleet.id}",
                                    placeholder="e.g. Inspector verified the load.")
                oc1, oc2 = st.columns(2)
                with oc1:
                    if st.button("Cancel", key=f"override_cancel_{fleet.id}",
                                 type="secondary", width="stretch"):
                        st.session_state["override_open_" + fleet.id] = False
                        st.rerun()
                with oc2:
                    if st.button("🔓 Confirm", key=f"override_confirm_{fleet.id}",
                                 type="primary", width="stretch"):
                        st.session_state["override_open_" + fleet.id] = False
                        _apply_override(fleet, reason, note)
                        st.rerun()

    with col3:
        if st.button("🔄 Run Re-Analysis", key=f"reanalyze_{fleet.id}",
                     width="stretch"):
            from services.anomaly_engine import AnomalyEngine
            engine = AnomalyEngine()
            decision = engine.run_full_analysis(fleet)
            result = getattr(engine, 'last_result', None)
            if result is not None:
                fleet.gemini_analysis = result.to_dict()
            fleet.status = decision.fleet_status
            if decision.severity in ("WARNING", "CRITICAL"):
                fleet.anomaly_history.append(AnomalyRecord(
                    anomaly_type=decision.anomaly_type,
                    severity=decision.severity,
                    timestamp=datetime.now(),
                    analysis_paragraph=result.analysis_paragraph if result
                    else decision.banner_message,
                    affected_items=result.affected_items if result else [],
                    recommended_actions=result.recommended_actions if result else [],
                ))
            fleet.last_updated = datetime.now()
            st.rerun()

    with col4:
        if fleet.status == FleetStatus.LOADING:
            if st.button("📋 Mark Inspected", key=f"inspected_{fleet.id}",
                         width="stretch"):
                if fleet.anomaly_history:
                    unresolved = [a for a in fleet.anomaly_history
                                  if not a.resolved]
                    fleet.status = (FleetStatus.ANOMALY_DETECTED if unresolved
                                    else FleetStatus.INSPECTED_CLEAR)
                else:
                    fleet.status = FleetStatus.INSPECTED_CLEAR
                fleet.last_updated = datetime.now()
                st.rerun()
