"""
services/anomaly_engine.py
=============================
Anomaly detection and classification engine.

Evaluates Gemini API output against business rules to classify anomalies
and trigger appropriate UI behaviors for the two scenarios:

  Scenario 1: Messy/Unstable Stacking (WARNING)
  Scenario 2: Unresolved Departure Risk (CRITICAL)
"""

from dataclasses import dataclass
from typing import Optional
from state.fleet_state import Fleet, FleetStatus, AnomalyRecord
from services.gemini_service import GeminiAnalysisResult


@dataclass
class FleetStateSnapshot:
    """Snapshot of departure-cue and loading state for a fleet."""
    loading_in_progress: bool = True
    doors_closing: bool = False
    truck_moving: bool = False
    anomaly_unresolved: bool = False


class AnomalyDecision:
    """The output decision from the anomaly engine."""

    def __init__(
        self,
        anomaly_type: str,
        severity: str,
        fleet_status: FleetStatus,
        ui_action: str,
        requires_override: bool = False,
        banner_message: str = "",
        banner_type: str = "info",
    ):
        self.anomaly_type = anomaly_type
        self.severity = severity
        self.fleet_status = fleet_status
        self.ui_action = ui_action
        self.requires_override = requires_override
        self.banner_message = banner_message
        self.banner_type = banner_type


class AnomalyEngine:
    """
    Evaluates Gemini output against business rules to classify anomalies
    and determine UI behaviors.
    """

    DISCREPANCY_WARNING_THRESHOLD = 0.40
    DISCREPANCY_CRITICAL_THRESHOLD = 0.70

    def __init__(self, gemini_service=None):
        from services.gemini_service import GeminiService
        self.gemini = gemini_service or GeminiService()
        # Stash of the most recent GeminiAnalysisResult (for UI persistence)
        self.last_result = None

    def evaluate(
        self,
        fleet: Fleet,
        gemini_result: GeminiAnalysisResult,
    ) -> AnomalyDecision:
        """
        Main evaluation method. Takes a Gemini analysis result and
        the current fleet state, and returns an AnomalyDecision.
        """
        snapshot = self._build_fleet_snapshot(fleet)

        # Check for departure risk first (Scenario 2)
        departure_decision = self._check_departure_risk(fleet, gemini_result, snapshot)
        if departure_decision is not None:
            return departure_decision

        # Check for messy stacking (Scenario 1)
        return self._check_messy_stacking(fleet, gemini_result, snapshot)

    def run_full_analysis(self, fleet: Fleet) -> AnomalyDecision:
        """
        Runs the full Gemini analysis pipeline on a fleet and returns
        the resulting anomaly decision.
        """
        cctv_frame_path = fleet.cctv_frame_path or self._get_default_cctv(fleet)
        depth_map_path = fleet.depth_map_path or self._get_default_depth(fleet)
        packing_plan = fleet.packing_layout
        manifest = fleet.manifest
        fleet_state = self._fleet_to_state_dict(fleet)

        # Run Gemini loading analysis
        gemini_result = self.gemini.analyze_loading(
            cctv_frame_path=cctv_frame_path,
            depth_map_path=depth_map_path,
            packing_plan=packing_plan,
            manifest=manifest,
            fleet_state=fleet_state,
        )
        self.last_result = gemini_result

        # Hard stop on a failed request: never let default/empty structured
        # fields be evaluated as a "clear" inspection, and never fall back to
        # the simulated engine. Surface the real error instead.
        if getattr(gemini_result, "status", "") == "FAILED":
            return AnomalyDecision(
                anomaly_type="GEMINI_REQUEST_FAILED",
                severity="NONE",
                fleet_status=fleet.status,
                ui_action="SHOW_GEMINI_FAILED",
                requires_override=False,
                banner_type="warning",
                banner_message=(
                    f"⚠️ GEMINI STATUS: FAILED (model: {gemini_result.model}) — "
                    f"{gemini_result.error or 'unknown error'}"
                ),
            )

        # Check for departure risk
        departure_result = self.gemini.detect_departure_risk(
            cctv_frame_path=cctv_frame_path,
            depth_map_path=depth_map_path,
            previous_analysis=gemini_result,
            fleet_state=fleet_state,
        )

        if departure_result.severity == "CRITICAL":
            return self._build_critical_decision(fleet, departure_result)

        return self._check_messy_stacking(
            fleet, gemini_result, self._build_fleet_snapshot(fleet)
        )

    def _build_fleet_snapshot(self, fleet: Fleet) -> FleetStateSnapshot:
        """Build a state snapshot from the Fleet dataclass."""
        has_unresolved = any(not a.resolved for a in fleet.anomaly_history)
        has_unresolved_warning = any(
            not a.resolved and a.severity == "WARNING"
            for a in fleet.anomaly_history
        )
        return FleetStateSnapshot(
            loading_in_progress=fleet.loading_in_progress,
            doors_closing=fleet.doors_closing,
            truck_moving=fleet.truck_moving,
            anomaly_unresolved=has_unresolved,
        )

    def _fleet_to_state_dict(self, fleet: Fleet) -> dict:
        """Convert Fleet to a state dict for Gemini service."""
        has_unresolved_warning = any(
            not a.resolved and a.severity == "WARNING"
            for a in fleet.anomaly_history
        )
        return {
            'loading_in_progress': fleet.loading_in_progress,
            'doors_closing': fleet.doors_closing,
            'truck_moving': fleet.truck_moving,
            'anomaly_unresolved': has_unresolved_warning,
            'fill_percentage': fleet.fill_percentage,
            'dock_number': fleet.dock_number,
        }

    def _check_departure_risk(
        self,
        fleet: Fleet,
        gemini_result: GeminiAnalysisResult,
        snapshot: FleetStateSnapshot,
    ) -> Optional[AnomalyDecision]:
        """
        Scenario 2: Unresolved Departure Risk (CRITICAL)

        Triggers when:
        - An anomaly from Scenario 1 remains uncorrected/ignored
        - System detects departure cues (doors closing OR truck moving)
        """
        departure_cues = snapshot.doors_closing or snapshot.truck_moving
        has_unresolved_warning = any(
            not a.resolved and a.severity == "WARNING"
            for a in fleet.anomaly_history
        )

        if departure_cues and has_unresolved_warning:
            dock_str = f"Dock {fleet.dock_number}"
            return AnomalyDecision(
                anomaly_type="UNRESOLVED_DEPARTURE_RISK",
                severity="CRITICAL",
                fleet_status=FleetStatus.BLOCKED,
                ui_action="SHOW_CRITICAL_BANNER",
                requires_override=True,
                banner_message=f"🚨 CRITICAL: DEPARTURE BLOCKED - UNRESOLVED ANOMALY DETECTED at {dock_str}",
                banner_type="critical",
            )
        return None

    def _check_messy_stacking(
        self,
        fleet: Fleet,
        gemini_result: GeminiAnalysisResult,
        snapshot: FleetStateSnapshot,
    ) -> AnomalyDecision:
        """
        Scenario 1: Messy/Unstable Stacking (WARNING)

        Triggers when:
        - Active loading in progress (rear doors open, dock engaged)
        - Gemini detects spatial misalignment, unstable stacking,
          heavy-over-fragile, or layout discrepancy
        """
        if gemini_result.severity == "WARNING" and gemini_result.anomaly_type == "MESSY_STACKING":
            dock_str = f"Dock {fleet.dock_number}"
            return AnomalyDecision(
                anomaly_type="MESSY_STACKING",
                severity="WARNING",
                fleet_status=FleetStatus.ANOMALY_DETECTED,
                ui_action="SHOW_WARNING_BANNER",
                requires_override=False,
                banner_message=f"⚠️ ANOMALY DETECTED: Messy Stacking at {dock_str}",
                banner_type="warning",
            )

        # Task 4: honor a CRITICAL severity from Gemini as a BLOCKED status
        # (the model is confident the loading is unsafe). The model's own
        # severity is authoritative — we never downgrade a CRITICAL to WARNING.
        if gemini_result.severity == "CRITICAL":
            return self._build_critical_decision(fleet, gemini_result)

        if gemini_result.severity == "NONE":
            return AnomalyDecision(
                anomaly_type="NONE",
                severity="NONE",
                fleet_status=FleetStatus.INSPECTED_CLEAR,
                ui_action="CLEAR_BANNER",
                requires_override=False,
                banner_message="",
                banner_type="info",
            )

        return AnomalyDecision(
            anomaly_type=gemini_result.anomaly_type,
            severity=gemini_result.severity,
            fleet_status=FleetStatus.ANOMALY_DETECTED,
            ui_action="SHOW_WARNING_BANNER",
            requires_override=False,
            banner_message=f"⚠️ ANOMALY DETECTED at Dock {fleet.dock_number}",
            banner_type="warning",
        )

    def _build_critical_decision(
        self, fleet: Fleet, gemini_result: GeminiAnalysisResult
    ) -> AnomalyDecision:
        dock_str = f"Dock {fleet.dock_number}"
        return AnomalyDecision(
            anomaly_type=gemini_result.anomaly_type,
            severity="CRITICAL",
            fleet_status=FleetStatus.BLOCKED,
            ui_action="SHOW_CRITICAL_BANNER",
            requires_override=True,
            banner_message=f"🚨 CRITICAL: DEPARTURE BLOCKED - UNRESOLVED ANOMALY DETECTED at {dock_str}",
            banner_type="critical",
        )

    def _get_default_cctv(self, fleet: Fleet) -> str:
        """Return default CCTV frame path based on dock number."""
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "assets", "cctv_frames", f"frame_dock_{fleet.dock_number}.jpg"
        )
        if os.path.exists(path):
            return path
        img_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "img")
        if os.path.exists(img_dir):
            for f in os.listdir(img_dir):
                if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                    return os.path.join(img_dir, f)
        return ""

    def _get_default_depth(self, fleet: Fleet) -> str:
        """Return default depth map path based on dock number."""
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "assets", "depth_maps", f"depth_dock_{fleet.dock_number}.png"
        )
        if os.path.exists(path):
            return path
        depth_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "my_photo_depth.png"
        )
        if os.path.exists(depth_path):
            return depth_path
        return ""
