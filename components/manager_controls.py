"""
components/manager_controls.py
===============================
Manager action strip + @st.dialog override modal for the tri-view panel.

- render_manager_controls(fleet): the always-visible action strip
  (Resolve / Override / Re-analyze / Mark Inspected), plus the
  "🖨 Print Invoice" download button once the dock has been
  marked finished (services/invoice_generator.py builds the .docx
  live from the fleet's packing data).
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

    # Gate controls on having actual packing data (not monitor placeholder)
    layout = fleet.packing_layout.get('layout', {}) if fleet.packing_layout else {}
    has_packed_items = bool(layout.get('packed_items'))
    # A dock can carry unresolved anomaly records even while LOADING (e.g. a
    # clean re-scan left it LOADING but earlier warnings are still open), so
    # surface the Resolve control whenever any unresolved record exists — not
    # only when the status flag is ANOMALY_DETECTED.
    has_unresolved_anomaly = bool(
        [a for a in fleet.anomaly_history if not a.resolved]
    )

    # --- Centered action group (matches approved mockup): a narrow bordered
    # box centered on the page holding TWO side-by-side buttons. Layout only —
    # every button keeps its original label, key, condition and action.
    left_pad, center_box, right_pad = st.columns([1, 2, 1])
    with center_box:
        with st.container(border=True):
            slot_left, slot_right = st.columns(2)

            # LEFT slot — single primary action picked by dock state:
            # Resolve (anomaly open) -> Manager Override (blocked) ->
            # Mark Inspected (loading, scan done).
            with slot_left:
                if has_unresolved_anomaly:
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
                elif fleet.status == FleetStatus.BLOCKED:
                    if st.button("🔓 Manager Override", key=f"override_{fleet.id}",
                                 type="primary", width="stretch"):
                        # Toggle an inline reason-code confirmation form
                        st.session_state["override_open_" + fleet.id] = True
                        st.rerun()
                elif has_packed_items and fleet.status == FleetStatus.LOADING:
                    if st.button("📋 Mark as Finished", key=f"inspected_{fleet.id}",
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
                elif has_packed_items and fleet.status == FleetStatus.INSPECTED_CLEAR:
                    # "Mark as Finished" was pressed — offer the printable
                    # Load & Packing Invoice, generated live from THIS dock's
                    # fleet data (no demo numbers, no hardcoding).
                    from services.invoice_generator import (
                        build_invoice_docx, invoice_doc_id, invoice_filename,
                        MIME_DOCX,
                    )
                    seq_key = f"invoice_seq_{fleet.dock_number}"
                    doc_id = invoice_doc_id(
                        fleet.dock_number, st.session_state.get(seq_key, 1))

                    def _bump_invoice_seq(key=seq_key):
                        # Bump AFTER a download so the next print gets a new
                        # document-ID suffix (…-01, …-02, …).
                        st.session_state[key] = st.session_state.get(key, 1) + 1

                    st.download_button(
                        "🖨 Print Invoice",
                        data=build_invoice_docx(fleet, doc_id=doc_id),
                        file_name=invoice_filename(fleet),
                        mime=MIME_DOCX,
                        key=f"invoice_{fleet.id}",
                        on_click=_bump_invoice_seq,
                        width="stretch",
                    )

            # RIGHT slot — Run Re-Analysis (always the right-hand button).
            with slot_right:
                if has_packed_items and st.button("🔄 Run Re-Analysis", key=f"reanalyze_{fleet.id}",
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

            # Override's inline reason form renders below the buttons, still
            # inside the centered box (unchanged behaviour, same keys).
            if fleet.status == FleetStatus.BLOCKED and st.session_state.get(
                    "override_open_" + fleet.id):
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
