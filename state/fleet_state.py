"""
state/fleet_state.py
=====================
Core state management layer for the Executive Fleet Diagnostic Center.

Defines the Fleet data model, FleetStatus enum, and utility functions
for managing shared state between the Loading Planner (View 1) and
the Executive Control Tower (View 2).
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Tuple, Any


class FleetStatus(Enum):
    """Fleet operational statuses with associated color codes."""
    LOADING = "LOADING"
    INSPECTED_CLEAR = "INSPECTED - CLEAR"
    ANOMALY_DETECTED = "ANOMALY DETECTED"
    BLOCKED = "BLOCKED FROM DEPARTURE"

    # Deprecated alias for backwards-compatible lookups
    PAUSED_AUDIT = "PAUSED / AUDIT REQUIRED"

    @property
    def color(self) -> str:
        """Return the CSS hex color for this status."""
        color_map = {
            "LOADING": "#3B82F6",               # Blue
            "INSPECTED - CLEAR": "#10B981",     # Green
            "ANOMALY DETECTED": "#F59E0B",      # Amber/Orange
            "BLOCKED FROM DEPARTURE": "#EF4444", # Red
            "PAUSED / AUDIT REQUIRED": "#F59E0B", # Amber (alias)
        }
        return color_map.get(self.value, "#6B7280")

    @property
    def color_name(self) -> str:
        """Human-readable color name for the status badge."""
        name_map = {
            "LOADING": "blue",
            "INSPECTED - CLEAR": "green",
            "ANOMALY DETECTED": "amber",
            "BLOCKED FROM DEPARTURE": "red",
            "PAUSED / AUDIT REQUIRED": "amber",
        }
        return name_map.get(self.value, "gray")


@dataclass
class AnomalyRecord:
    """Records a single anomaly event for audit history."""
    anomaly_type: str
    severity: str  # "WARNING" or "CRITICAL"
    timestamp: datetime
    analysis_paragraph: str
    affected_items: List[str] = field(default_factory=list)
    recommended_actions: List[str] = field(default_factory=list)
    resolved: bool = False
    resolved_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Serialize AnomalyRecord to a JSON-compatible dict."""
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        if self.resolved_at is not None:
            d['resolved_at'] = self.resolved_at.isoformat()
        return d


@dataclass
class Fleet:
    """
    Represents a truck currently stationed at a loading dock.
    This is the shared data model between View 1 and View 2.
    """
    id: str                              # e.g., "TK-04"
    dock_number: int                     # e.g., 2
    truck_dimensions: Tuple[float, float, float]  # (W, H, D) in meters
    manifest: List[Dict[str, Any]]       # Original cargo items from View 1
    packing_layout: Dict[str, Any]     # Optimal packing result (py3dbp output)
    status: FleetStatus = FleetStatus.LOADING
    fill_percentage: float = 0.0         # Volumetric fill % (0-100)
    cctv_frame_path: str = ""            # Path to current CCTV frame image
    depth_map_path: str = ""             # Path to depth map image
    gemini_analysis: Dict[str, Any] = field(default_factory=dict)
    anomaly_history: List[AnomalyRecord] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    # Departure-cue detection state
    doors_closing: bool = False
    truck_moving: bool = False
    loading_in_progress: bool = True     # True when rear doors open & dock engaged
    truck_name: str = ""                  # Descriptive name for the truck
    source: str = "live"                  # "live" (worker) | "mock" (demo dock)

    def to_dict(self) -> dict:
        """Serialize Fleet to a JSON-compatible dict (for persistence or API)."""
        d = asdict(self)
        # asdict() leaves datetime objects raw; convert for JSON compatibility
        d['created_at'] = self.created_at.isoformat()
        d['last_updated'] = self.last_updated.isoformat()
        d['anomaly_history'] = [r.to_dict() for r in self.anomaly_history]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'Fleet':
        """Deserialize Fleet from a dict (accepts str or datetime values)."""
        data = data.copy()
        if 'status' in data:
            data['status'] = FleetStatus(data['status'])
        for key in ('created_at', 'last_updated'):
            if key in data and isinstance(data[key], str):
                data[key] = datetime.fromisoformat(data[key])
        # Rebuild anomaly_history records
        history = []
        for rec in data.get('anomaly_history', []):
            if isinstance(rec, dict):
                for key in ('timestamp', 'resolved_at'):
                    if isinstance(rec.get(key), str):
                        rec[key] = datetime.fromisoformat(rec[key])
                history.append(AnomalyRecord(**rec))
        data['anomaly_history'] = history
        return cls(**data)
# --- SESSION STATE UTILITIES ---

def initialize_session_state():
    """
    Initialize all required session state variables for both View 1 and View 2.
    Call this at the top of app.py before any rendering.
    """
    import streamlit as st

    if 'view_mode' not in st.session_state:
        st.session_state.view_mode = 'worker'

    if 'active_fleets' not in st.session_state:
        st.session_state.active_fleets = []

    if 'selected_fleet_id' not in st.session_state:
        st.session_state.selected_fleet_id = None

    if 'gemini_analyses' not in st.session_state:
        st.session_state.gemini_analyses = {}

    if 'anomaly_banners' not in st.session_state:
        st.session_state.anomaly_banners = []

    if 'color_map' not in st.session_state:
        st.session_state.color_map = {}

    # Hybrid dock registry (DockState wrappers for the 3 fixed docks)
    from state.dock_state import initialize_dock_registry
    initialize_dock_registry()


def get_fleet_by_id(fleet_id: str) -> 'Fleet':
    """Retrieve a fleet by its ID from session state."""
    import streamlit as st
    if 'active_fleets' not in st.session_state:
        return None
    for fleet in st.session_state.active_fleets:
        if fleet.id == fleet_id:
            return fleet
    return None


def select_fleet(fleet_id: str):
    """Set the currently selected fleet in session state."""
    import streamlit as st
    st.session_state.selected_fleet_id = fleet_id

def build_fleet_from_packing_result(
    manifest: List[Dict], packer: Any,
    truck_w: float, truck_h: float, truck_d: float,
    truck_name: str = "",
    dock_number: int = 1,
) -> Optional['Fleet']:
    """Pure builder: construct a Fleet object from a py3dbp packing result.

    Does **not** touch session state — returns a fresh Fleet whose mutable
    fields are ready to be either appended (new fleet) or used to upsert an
    existing fleet in-place (re-render of the same dock).

    The caller is responsible for assigning ``fleet.id`` before insertion.
    """
    bins = getattr(packer, 'bins', [])
    if not bins:
        return None

    bin_obj = bins[0]
    packed_items = getattr(bin_obj, 'items', [])
    unfitted = getattr(bin_obj, 'unfitted_items', [])

    layout_data = {
        'part_number': bin_obj.partno,
        'WHD': (bin_obj.width, bin_obj.height, bin_obj.depth),
        'packed_items': [],
        'unfitted_items': [],
        'gravity': getattr(bin_obj, 'gravity', [0, 0, 0, 0]),
    }

    manifest_lookup = {
        f"{item['name']} #{i+1}": item
        for item in manifest
        for i in range(item.get('quantity', 1))
    }

    packed_volume = 0.0

    for item in packed_items:
        pos = item.position
        dim = item.getDimension()
        m_data = manifest_lookup.get(item.name, {})
        item_volume = float(dim[0]) * float(dim[1]) * float(dim[2])
        packed_volume += item_volume
        layout_data['packed_items'].append({
            'name': item.name,
            'part_number': item.partno,
            'position': [float(pos[0]), float(pos[1]), float(pos[2])],
            'dimensions': [float(dim[0]), float(dim[1]), float(dim[2])],
            'weight': float(item.weight),
            'max_load': m_data.get('max_load', 0),
            'fragile': m_data.get('fragile', False),
            'color': m_data.get('color', ''),
        })

    for item in unfitted:
        layout_data['unfitted_items'].append({
            'name': item.name,
            'part_number': item.partno,
            'weight': float(item.weight),
        })

    truck_volume_cm = float(truck_w) * float(truck_h) * float(truck_d) * 1e6
    fill_pct = min(100.0, (packed_volume / truck_volume_cm) * 100) if truck_volume_cm > 0 else 0.0

    total_items_expected = sum(item.get('quantity', 1) for item in manifest)
    packed_count = len(packed_items)

    manifest_summary = []
    for m_item in manifest:
        packed_for_item = sum(
            1 for p in packed_items
            if p.name.split('#')[0].strip() == m_item['name']
        )
        manifest_summary.append({
            'name': m_item['name'],
            'quantity': m_item.get('quantity', 1),
            'total_expected': m_item.get('quantity', 1),
            'packed': packed_for_item,
            'remaining': max(0, m_item.get('quantity', 1) - packed_for_item),
            'fragile': m_item.get('fragile', False),
            'max_load': m_item.get('max_load', 100),
        })

    fleet = Fleet(
        id="TK-TEMP",  # assigned by the caller (register/upsert)
        dock_number=dock_number,
        truck_dimensions=(truck_w, truck_h, truck_d),
        manifest=manifest,
        packing_layout={
            'layout': layout_data,
            'manifest_summary': manifest_summary,
            'total_items_expected': total_items_expected,
            'packed_count': packed_count,
            'unfitted_count': len(unfitted),
            'fill_percentage': round(fill_pct, 1),
        },
        status=FleetStatus.LOADING,
        fill_percentage=round(fill_pct, 1),
        truck_name=truck_name,
        loading_in_progress=True,
        doors_closing=False,
        truck_moving=False,
        source="live",
    )

    return fleet


def register_fleet_from_packing_result(
    manifest: List[Dict], packer: Any,
    truck_w: float, truck_h: float, truck_d: float,
    truck_name: str = "",
    dock_number: int = 1,
) -> Optional['Fleet']:
    """Called when View 1 completes a packing calculation.

    Builds a Fleet via :func:`build_fleet_from_packing_result` and upserts it
    into session state.  If a live fleet already exists for *dock_number*
    (e.g. the Dock-1 monitor placeholder or a previous re-render), its
    mutable fields are refreshed **in place** — preserving fleet identity —
    so re-renders never spawn duplicate fleets.
    """
    import streamlit as st
    initialize_session_state()

    fleet = build_fleet_from_packing_result(
        manifest, packer, truck_w, truck_h, truck_d,
        truck_name=truck_name, dock_number=dock_number,
    )
    if fleet is None:
        return None

    # Upsert: find an existing live fleet for this dock
    existing = None
    for f in st.session_state.get('active_fleets', []):
        if f.source == "live" and f.dock_number == dock_number:
            existing = f
            break

    if existing is not None:
        # Update in place — keep identity (id, created_at), refresh data
        existing.dock_number = dock_number
        existing.truck_dimensions = fleet.truck_dimensions
        existing.manifest = fleet.manifest
        existing.packing_layout = fleet.packing_layout
        existing.fill_percentage = fleet.fill_percentage
        existing.truck_name = fleet.truck_name
        existing.loading_in_progress = True
        existing.doors_closing = False
        existing.truck_moving = False
        existing.gemini_analysis = {}
        existing.status = FleetStatus.LOADING
        existing.last_updated = datetime.now()
        fleet = existing
    else:
        # New fleet — assign a sequential id and append
        fleet.id = f"TK-{len(st.session_state.active_fleets) + 1:02d}"
        st.session_state.active_fleets.append(fleet)

    st.session_state.last_updated = datetime.now()

    # Link this fleet into the hybrid dock registry
    from state.dock_state import upsert_dock_fleet, set_dock_stage, DockStage
    upsert_dock_fleet(dock_number, fleet.id)
    set_dock_stage(dock_number, DockStage.LOADING)

    return fleet


def add_anomaly_record(fleet: 'Fleet', anomaly: AnomalyRecord):
    """Append an anomaly to a fleet's history and update its status."""
    import streamlit as st
    fleet.anomaly_history.append(anomaly)
    if anomaly.severity == "CRITICAL":
        fleet.status = FleetStatus.BLOCKED
    elif anomaly.severity == "WARNING":
        fleet.status = FleetStatus.ANOMALY_DETECTED
    fleet.last_updated = datetime.now()


def resolve_anomaly(fleet: 'Fleet'):
    """Mark all unresolved anomalies as resolved and reset status."""
    import streamlit as st
    for anomaly in reversed(fleet.anomaly_history):
        if not anomaly.resolved:
            anomaly.resolved = True
            anomaly.resolved_at = datetime.now()
    has_unresolved_warning = any(
        not a.resolved and a.severity == "WARNING"
        for a in fleet.anomaly_history
    )
    has_unresolved_critical = any(
        not a.resolved and a.severity == "CRITICAL"
        for a in fleet.anomaly_history
    )
    if has_unresolved_critical:
        fleet.status = FleetStatus.BLOCKED
    elif has_unresolved_warning:
        fleet.status = FleetStatus.ANOMALY_DETECTED
    else:
        fleet.status = FleetStatus.INSPECTED_CLEAR
    fleet.last_updated = datetime.now()

    # Clear rendered banner markers for this fleet so banners can
    # re-appear if a new anomaly is detected later.
    if 'rendered_warnings' in st.session_state:
        st.session_state.rendered_warnings = [
            k for k in st.session_state.rendered_warnings
            if not k.startswith(f"warning_{fleet.id}")
        ]
    if 'rendered_criticals' in st.session_state:
        st.session_state.rendered_criticals = [
            k for k in st.session_state.rendered_criticals
            if not k.startswith(f"critical_{fleet.id}")
        ]
