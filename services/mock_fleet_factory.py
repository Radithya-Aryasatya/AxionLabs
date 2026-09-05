"""
services/mock_fleet_factory.py
==============================
Editable placeholder mock fleets for the Hybrid Executive Fleet Diagnostic Center.

Docks 2, 3, 4 are IDENTICAL pages to Dock 1 (same tri-view panel) but driven by
EDITABLE placeholder files you can swap without touching code:

  1. CCTV feed  ->  assets/cctv_frames/cctv_dock{N}.jpg   (replace the file)
  2. 3D layout  ->  assets/mock_docks/mock_layout_dock{N}.json  (edit the JSON)

On first run each missing file is written with a sensible default
(Dock 2 = INSPECTED-CLEAR, Dock 3 = BLOCKED, Dock 4 = LOADING) so the demo works
out-of-the-box. Edit the JSON -> the page updates on next rerun.
"""

import json
import os
import shutil
from datetime import datetime

from state.fleet_state import Fleet, FleetStatus, AnomalyRecord
from state.dock_state import (
    upsert_dock_fleet, set_dock_stage, set_analysis_source,
    DockStage, AnalysisSource,
)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_IMG_DIR = os.path.join(_BASE_DIR, "img")
_CCTV_DIR = os.path.join(_BASE_DIR, "assets", "cctv_frames")
_DEPTH_DIR = os.path.join(_BASE_DIR, "assets", "depth_maps")
_MOCK_DIR = os.path.join(_BASE_DIR, "assets", "mock_docks")


# --- CCTV / depth asset pinning (deterministic) ---

def _ensure_dirs():
    os.makedirs(_CCTV_DIR, exist_ok=True)
    os.makedirs(_DEPTH_DIR, exist_ok=True)
    os.makedirs(_MOCK_DIR, exist_ok=True)


def _available_images():
    if not os.path.exists(_IMG_DIR):
        return []
    return [os.path.join(_IMG_DIR, f) for f in sorted(os.listdir(_IMG_DIR))
            if f.lower().endswith(('.jpg', '.jpeg', '.png'))]


def ensure_dock_assets(dock_number: int):
    """Pin a deterministic CCTV frame + depth map for a dock.
    Returns (cctv_path, depth_path). Copies from img/ if needed."""
    _ensure_dirs()
    images = _available_images()

    cctv_name = f"cctv_dock{dock_number}.jpg"
    cctv_path = os.path.join(_CCTV_DIR, cctv_name)
    if not os.path.exists(cctv_path) and images:
        idx = (dock_number - 1) % len(images)
        shutil.copy2(images[idx], cctv_path)

    depth_name = f"depth_dock_{dock_number}.png"
    depth_path = os.path.join(_DEPTH_DIR, depth_name)
    if not os.path.exists(depth_path):
        fallback = os.path.join(_BASE_DIR, "my_photo_depth.png")
        if os.path.exists(fallback):
            shutil.copy2(fallback, depth_path)
        elif os.path.exists(cctv_path):
            shutil.copy2(cctv_path, depth_path)

    return cctv_path, depth_path


# --- Editable placeholder layouts ---

def _default_layout(dock_number: int) -> dict:
    """Return the default editable layout dict for a mock dock.
    Edit the generated JSON file to customise the page."""
    packed = [
        {'name': 'Crate-A #1', 'part_number': f'M{dock_number}-0',
         'position': [0, 0, 0], 'dimensions': [80, 80, 80],
         'weight': 40, 'fragile': False},
        {'name': 'Crate-A #2', 'part_number': f'M{dock_number}-1',
         'position': [80, 0, 0], 'dimensions': [80, 80, 80],
         'weight': 40, 'fragile': False},
        {'name': 'Crate-B #1', 'part_number': f'M{dock_number}-2',
         'position': [0, 80, 0], 'dimensions': [80, 80, 80],
         'weight': 25, 'fragile': True},
    ]
    base = {
        'id': f'TK-MOCK-0{dock_number}',
        'truck_name': f'Placeholder Truck Dock-{dock_number}',
        'truck_dimensions': [2.0, 2.0, 4.0],
        'fill_percentage': 72.5,
        'loading_in_progress': False,
        'doors_closing': False,
        'truck_moving': False,
        'manifest': [
            {'name': 'Crate-A', 'quantity': 2, 'fragile': False, 'max_load': 100},
            {'name': 'Crate-B', 'quantity': 1, 'fragile': True, 'max_load': 60},
        ],
        'packed_items': packed,
        'manifest_summary': [
            {'name': 'Crate-A', 'quantity': 2, 'packed': 2, 'remaining': 0,
             'fragile': False, 'max_load': 100},
            {'name': 'Crate-B', 'quantity': 1, 'packed': 1, 'remaining': 0,
             'fragile': True, 'max_load': 60},
        ],
        'total_items_expected': 3,
        'packed_count': 3,
        'unfitted_count': 0,
    }

    base.update({
        'status': 'LOADING',
        'loading_in_progress': True,
        'doors_closing': False,
        'truck_moving': False,
        'gemini_analysis': {},
        'anomaly_history': [],
    })
    return base


def _load_mock_layout(dock_number: int) -> dict:
    """Load a mock dock's editable layout from its JSON file,
    writing the default file if it doesn't exist yet."""
    _ensure_dirs()
    path = os.path.join(_MOCK_DIR, f"mock_layout_dock{dock_number}.json")
    if not os.path.exists(path):
        data = _default_layout(dock_number)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        return data
    with open(path) as f:
        return json.load(f)


# --- Deterministic 3D twin figure builder ---

def _build_twin_figure(packed_items, part_number):
    """Build a lightweight Plotly 3D figure from packed-item dicts.
    Deterministic — no randomness — so the twin is stable across reruns."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None

    traces = []
    if packed_items:
        max_x = max(i['position'][0] + i['dimensions'][0] for i in packed_items)
        max_y = max(i['position'][1] + i['dimensions'][1] for i in packed_items)
        max_z = max(i['position'][2] + i['dimensions'][2] for i in packed_items)
    else:
        max_x, max_y, max_z = 200, 200, 400
    corners = [(0, 0, 0), (max_x, 0, 0), (max_x, max_y, 0), (0, max_y, 0),
               (0, 0, max_z), (max_x, 0, max_z), (max_x, max_y, max_z), (0, max_y, max_z)]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
             (0, 4), (1, 5), (2, 6), (3, 7)]
    for a, b in edges:
        traces.append(go.Scatter3d(
            x=[corners[a][0], corners[b][0]],
            y=[corners[a][1], corners[b][1]],
            z=[corners[a][2], corners[b][2]],
            mode='lines', line=dict(color='#475569', width=2),
            showlegend=False, hoverinfo='skip',
        ))

    palette = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#06B6D4"]
    for i, item in enumerate(packed_items):
        px, py, pz = item['position']
        dx, dy, dz = item['dimensions']
        color = palette[i % len(palette)]
        v = [(px, py, pz), (px + dx, py, pz), (px + dx, py + dy, pz), (px, py + dy, pz),
             (px, py, pz + dz), (px + dx, py, pz + dz),
             (px + dx, py + dy, pz + dz), (px, py + dy, pz + dz)]
        faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
                 (2, 3, 7, 6), (0, 3, 7, 4), (1, 2, 6, 5)]
        for f in faces:
            traces.append(go.Mesh3d(
                x=[v[idx][0] for idx in f], y=[v[idx][1] for idx in f],
                z=[v[idx][2] for idx in f],
                color=color, opacity=0.7, alphahull=0, hoverinfo='skip',
                showlegend=False,
            ))

    fig = go.Figure(data=traces)
    fig.update_layout(
        scene=dict(xaxis_title='X', yaxis_title='Y', zaxis_title='Z',
                   aspectmode='data'),
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
    )
    return fig


def _build_fleet_from_layout(data: dict):
    """Construct a Fleet + packed_items from an editable layout dict."""
    packed = data['packed_items']
    layout_data = {
        'part_number': f"MOCK-D{data.get('dock_number', '?')}",
        'WHD': (200.0, 200.0, 400.0),
        'packed_items': packed,
        'unfitted_items': [],
        'gravity': [25, 25, 25, 25],
    }
    status_map = {
        'LOADING': FleetStatus.LOADING,
        'INSPECTED_CLEAR': FleetStatus.INSPECTED_CLEAR,
        'ANOMALY DETECTED': FleetStatus.ANOMALY_DETECTED,
        'BLOCKED': FleetStatus.BLOCKED,
    }
    status = status_map.get(data.get('status', 'LOADING'), FleetStatus.LOADING)

    history = []
    for rec in data.get('anomaly_history', []):
        history.append(AnomalyRecord(
            anomaly_type=rec.get('anomaly_type', 'UNKNOWN'),
            severity=rec.get('severity', 'WARNING'),
            timestamp=datetime.now(),
            analysis_paragraph=rec.get('analysis_paragraph', ''),
            affected_items=rec.get('affected_items', []),
            recommended_actions=rec.get('recommended_actions', []),
            resolved=rec.get('resolved', False),
        ))

    fleet = Fleet(
        id=data.get('id', 'TK-MOCK'),
        dock_number=data.get('dock_number', 2),
        truck_dimensions=tuple(data.get('truck_dimensions', [2.0, 2.0, 4.0])),
        manifest=data.get('manifest', []),
        packing_layout={
            'layout': layout_data,
            'manifest_summary': data.get('manifest_summary', []),
            'total_items_expected': data.get('total_items_expected', 0),
            'packed_count': data.get('packed_count', 0),
            'unfitted_count': data.get('unfitted_count', 0),
            'fill_percentage': data.get('fill_percentage', 0.0),
        },
        status=status,
        fill_percentage=data.get('fill_percentage', 0.0),
        truck_name=data.get('truck_name', 'Placeholder Truck'),
        loading_in_progress=data.get('loading_in_progress', False),
        doors_closing=data.get('doors_closing', False),
        truck_moving=data.get('truck_moving', False),
        source='mock',
        gemini_analysis=data.get('gemini_analysis', {}),
        anomaly_history=history,
    )
    return fleet, packed


# --- Seeding ---

# Content-hash cache: tracks the JSON file content per dock so we can
# re-seed a mock dock ONLY when its layout file actually changed. This lets
# Task-4 state (operator CCTV selection, scan results, notifications)
# survive ordinary Streamlit reruns while preserving the "edit the JSON ->
# see it on next rerun" feature.
#
#   st.session_state['mock_layout_hashes'] = {dock_number: sha256, ...}
#   st.session_state['mock_fleet_ids']     = {dock_number: fleet_id, ...}


def _layout_file_path(dock_number: int) -> str:
    return os.path.join(_MOCK_DIR, f"mock_layout_dock{dock_number}.json")


def _file_content_hash(path: str) -> str:
    """SHA-256 of the file contents (or "" if the file is unreadable)."""
    try:
        with open(path, 'rb') as fh:
            import hashlib
            return hashlib.sha256(fh.read()).hexdigest()
    except Exception:
        return ""


def _mock_fleet_id_map() -> dict:
    import streamlit as st
    return st.session_state.setdefault('mock_fleet_ids', {})


def _forget_mock_fleet_id(dock_number: int):
    import streamlit as st
    m = st.session_state.get('mock_fleet_ids', {})
    m.pop(dock_number, None)


def _set_mock_fleet_id(dock_number: int, fleet_id: str):
    import streamlit as st
    st.session_state.setdefault('mock_fleet_ids', {})[dock_number] = fleet_id


def seed_mock_docks():
    """
    Create editable Dock 2, 3, 4 mock fleets (identical placeholder pages),
    pin their CCTV assets, build their twin figures, and link them into
    the dock registry.

    Hash-idempotent: a dock is re-seeded ONLY when its JSON layout file's
    content-hash changed since the last seeding (or the fleet is missing).
    Ordinary Streamlit reruns — which used to wipe operator CCTV selections
    and scan results on every script re-execution — are now no-ops for the
    unchanged docks. Explicit demo reset still works via ``reseed_mock_docks``
    (clears the hash cache so the next seeding is forced).
    """
    import streamlit as st
    from state.fleet_state import initialize_session_state
    initialize_session_state()

    fleet_id_map = _mock_fleet_id_map()

    for dock_number in (2, 3, 4):
        layout_path = _layout_file_path(dock_number)
        new_hash = _file_content_hash(layout_path)
        old_hash = st.session_state.get('mock_layout_hashes', {}).get(dock_number)
        existing_fleet = None
        if fleet_id_map.get(dock_number):
            for f in st.session_state.get('active_fleets', []):
                if f.id == fleet_id_map[dock_number] and f.source == 'mock':
                    existing_fleet = f
                    break

        # Re-seed only when content changed or the fleet is gone.
        if existing_fleet is not None and new_hash == old_hash:
            # Nothing changed for this dock — leave its state intact.
            # But still make sure the dock registry linkage is present.
            upsert_dock_fleet(dock_number, existing_fleet.id)
            continue

        # Need to (re)build this mock dock.
        data = _load_mock_layout(dock_number)
        data['dock_number'] = dock_number  # ensure correct dock linkage
        fleet, packed = _build_fleet_from_layout(data)
        cctv, depth = ensure_dock_assets(dock_number)
        fleet.cctv_frame_path = cctv
        fleet.depth_map_path = depth

        # Replace the old fleet in the active list (preserve list ordering).
        st.session_state.active_fleets = [
            f for f in st.session_state.get('active_fleets', [])
            if not (f.source == 'mock' and f.dock_number == dock_number)
        ]
        st.session_state.active_fleets.append(fleet)

        # Per-dock twin figure so each dock shows its own layout
        fig = _build_twin_figure(packed, f'MOCK-D{dock_number}')
        if fig is not None:
            st.session_state.setdefault('fleet_3d_figures', {})[
                f'MOCK-D{dock_number}'] = fig

        upsert_dock_fleet(dock_number, fleet.id)
        set_dock_stage(dock_number, DockStage.MONITORED)
        set_analysis_source(dock_number, AnalysisSource.NONE)

        fleet_id_map[dock_number] = fleet.id
        st.session_state.setdefault('mock_layout_hashes', {})[dock_number] = new_hash

    # Ensure Dock 1 always has a monitor fleet for the executive dashboard
    from services.dock_pipeline import ensure_dock1_monitor_fleet
    ensure_dock1_monitor_fleet()

    st.session_state.last_updated = datetime.now()


def reseed_mock_docks():
    """Reset Docks 2, 3, 4 to their opening demo state (between rehearsals).

    Clears the content-hash cache so the next ``seed_mock_docks`` is forced
    to rebuild every mock dock from its JSON file, wiping any operator CCTV
    selections and scan results in the process.
    """
    import streamlit as st
    from state.notifications import clear_all
    clear_all()
    # Clear the hash cache and fleet-id map to force a full rebuild.
    st.session_state.pop('mock_layout_hashes', None)
    st.session_state.pop('mock_fleet_ids', None)
    seed_mock_docks()
    st.session_state.last_updated = datetime.now()

