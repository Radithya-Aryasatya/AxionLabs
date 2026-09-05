#app.py
import streamlit as st
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
from dataclasses import dataclass
from orientation_editor import launch_orientation_editor
import pandas as pd
import math
import json
import streamlit.components.v1 as components
from html import escape as html_escape
import os
from dotenv import load_dotenv

# --- Executive Fleet Diagnostic Center imports ---
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from state.fleet_state import (
    initialize_session_state, register_fleet_from_packing_result, Fleet,
)
from components.header import render_header
from executive_dashboard import render_executive_dashboard

# --- STALE-MODULE GUARD (pitch-day insurance) ---------------------------------
# Streamlit re-executes app.py on every rerun but does NOT re-import edited
# modules — a running server keeps whichever class versions were loaded at
# startup. If an old `state.fleet_state` (pre-`source` field) is ever left
# cached in sys.modules, fail fast with an actionable message instead of the
# cryptic `TypeError: Fleet.__init__() got an unexpected keyword argument
# 'source'` from deep inside seed_mock_docks().
if not hasattr(Fleet, "source"):
    st.error(
        "⚠️ **Stale module cache detected.** The running Streamlit process has an "
        "old version of `state/fleet_state.py` loaded (missing `Fleet.source`). "
        "Stop the server (Ctrl+C), restart with `streamlit run app.py`, then "
        "hard-refresh the browser (Ctrl+Shift+R)."
    )
    st.stop()

# Task 4: extend the stale-module guard to the new DockState fields.
# If an old `state.dock_state` (pre-`cctv_updated_at`) is ever left cached in
# sys.modules, fail fast with an actionable message.
try:
    from state.dock_state import DockState
    if not hasattr(DockState, "cctv_updated_at"):
        st.error(
            "⚠️ **Stale module cache detected.** The running Streamlit process has an "
            "old version of `state/dock_state.py` loaded (missing `DockState.cctv_updated_at`). "
            "Stop the server (Ctrl+C), restart with `streamlit run app.py`, then "
            "hard-refresh the browser (Ctrl+Shift+R)."
        )
        st.stop()
except Exception:
    pass

# --- APP INITIALIZATION ---
load_dotenv()
api_key = os.getenv("API_KEY")

# Initialize session state (for both views)
initialize_session_state()

# Ensure placeholder mock docks exist in both views from first paint
from services.mock_fleet_factory import seed_mock_docks
seed_mock_docks()

# Ensure Dock 1 always has a monitor fleet for the executive dashboard
from services.dock_pipeline import ensure_dock1_monitor_fleet
ensure_dock1_monitor_fleet()

# --- VIEW TOGGLE ---
render_header()

# Route to View 2 (Executive Control Tower) if selected
if st.session_state.get('view_mode', 'worker') == 'executive':
    render_executive_dashboard()
    st.stop()

# --- DATA STRUCTURE ARCHITECTURE ---
@dataclass
class PackedItem:
    name: str
    x: float
    y: float
    z: float
    w: float
    h: float
    d: float
    weight: float
    
    max_load: float

# --- MODULAR BUSINESS LOGIC LAYER ---
def get_color(name):

    palette = [
        "#1f77b4",   # blue
        "#ff7f0e",   # orange
        "#2ca02c",   # green
        "#d62728",   # red
        "#9467bd",   # purple
        "#8c564b",   # brown
        "#e377c2",   # pink
        "#17becf",   # cyan
        "#bcbd22",   # olive
        "#7f7f7f"    # gray
    ]

    if "color_map" not in st.session_state:
        st.session_state.color_map = {}

    # Remove instance number
    base_name = name.split("#")[0].strip()

    if base_name not in st.session_state.color_map:
        idx = len(st.session_state.color_map) % len(palette)
        st.session_state.color_map[base_name] = palette[idx]

    return st.session_state.color_map[base_name]

def calculate_overlap_area(c_x: float, c_w: float, c_z: float, c_d: float, 
                           s_x: float, s_w: float, s_z: float, s_d: float) -> float:
    """Calculates the 2D intersection area (X-Z plane) between two items."""
    x_overlap = max(0.0, min(c_x + c_w, s_x + s_w) - max(c_x, s_x))
    z_overlap = max(0.0, min(c_z + c_d, s_z + s_d) - max(c_z, s_z))
    return x_overlap * z_overlap

def validate_cargo_dimensions(manifest):
    """
    Prevent invalid cargo dimensions from reaching py3dbp.

    Every cargo item must have finite, strictly positive
    width, height, and depth.
    """

    invalid_items = []

    for item in manifest:

        dimensions = {
            "width": item.get("w"),
            "height": item.get("h"),
            "depth": item.get("d")
        }

        for dimension_name, value in dimensions.items():

            try:
                value = float(value)
            except (TypeError, ValueError):
                invalid_items.append(
                    f"{item.get('name', 'Unnamed')} → {dimension_name} is not numeric."
                )
                continue

            if not math.isfinite(value) or value <= 0:
                invalid_items.append(
                    f"{item.get('name', 'Unnamed')} → "
                    f"{dimension_name} must be greater than 0."
                )

    return invalid_items

def calculate_utilization(items: list[PackedItem], truck_volume: float) -> float:
    if truck_volume <= 0:
        return 0.0
    used_volume = sum((item.w * item.h * item.d) for item in items)
    return (used_volume / truck_volume) * 100

def is_layout_safe(items):

    load_distribution, _ = calculate_load_distribution(items)

    for item in items:

        if load_distribution[item.name] > item.max_load:
            return False

    return True

def calculate_load_distribution(items: list[PackedItem]) -> tuple[dict[str, float], dict[str, list[str]]]:
    EPS = 1e-3
    sorted_items = sorted(items, key=lambda item: item.y, reverse=True)
    
    weight_on_top = {item.name: 0.0 for item in items}
    support_graph = {item.name: [] for item in items}
    
    for current in sorted_items:
        total_downward_force = current.weight + weight_on_top[current.name]
        
        # Identify supporters and their respective contact areas
        supporters = []
        total_contact_area = 0.0
        
        for other in items:
            if other.name == current.name:
                continue
            
            # Check for strict vertical physical contact
            if abs(current.y - (other.y + other.h)) < EPS:
                area = calculate_overlap_area(
                    current.x, current.w, current.z, current.d,
                    other.x, other.w, other.z, other.d
                )
                if area > 0:
                    supporters.append((other, area))
                    total_contact_area += area
                    support_graph[other.name].append(current.name)
        
        # Propagate loads proportionally based on contact surface area
        if supporters and total_contact_area > 0:
            for sup, area in supporters:
                area_ratio = area / total_contact_area
                distributed_force = total_downward_force * area_ratio
                weight_on_top[sup.name] += distributed_force
                
    return weight_on_top, support_graph

def calculate_offloading_score(items, manifest_lookup):
    """
    Higher score = easier unloading.

    Sequence 1 should be closest to truck door.
    Sequence 2 slightly deeper.
    etc.
    """

    if len(items) == 0:
        return 100.0

    max_depth = max(i.z + i.d for i in items)

    total_error = 0.0

    max_sequence = max(
        manifest_lookup[i.name]["sequence"]
        for i in items
    )

    if max_sequence == 1:
        return 100.0

    for item in items:

        desired_position = (
            (manifest_lookup[item.name]["sequence"] - 1)
            / (max_sequence - 1)
        )

        actual_position = 1 - (
            item.z / max_depth
        )

        total_error += abs(
            desired_position - actual_position
        )

    average_error = total_error / len(items)

    score = max(
        0,
        100 - average_error * 100
    )

    return score

def score_to_stars(score):
    """
    Converts a percentage score into a star rating.
    """

    if score >= 95:
        return "★★★★★", "Excellent"

    elif score >= 70:
        return "★★★★☆", "Good"

    elif score >= 45:
        return "★★★☆☆", "Fair"

    elif score >= 25:
        return "★★☆☆☆", "Poor"

    else:
        return "★☆☆☆☆", "Very Poor"

def build_loading_priority(manifest):
    """
    Returns the loading order.

    Higher priority items are packed FIRST.
    """

    return sorted(
        manifest,
        key=lambda item: (

            # unload later first
            -item["sequence"],

            # fragile goes later
            item["max_load"],

            # larger volume first
            -(item["w"] * item["h"] * item["d"]),

            # heavier first
            -item["weight"]

        )
    )

def generate_axis_ticks(max_val: float, default_step: float = 5.0) -> list[float]:
    """Generates tick intervals up to max_val, explicitly adding max_val to include the final grid line."""
    step = default_step if max_val <= 40 else 10.0
    ticks = []
    curr = 0.0
    while curr < max_val:
        ticks.append(round(curr, 2))
        curr += step
    if round(max_val, 2) not in ticks:
        ticks.append(round(max_val, 2))
    return sorted(list(set(ticks)))

# --- CAMERA / DEPTH-PEELING LOGIC ---
def sort_items_by_camera_depth(
    items: list[PackedItem],
    eye: dict,
    truck_dims: tuple[float, float, float]
) -> list[PackedItem]:
    """
    Orders packed items from farthest-from-camera to closest-to-camera, using the
    same coordinate mapping as the 3D plot (plot x = width, plot y = truck depth,
    plot z = height).

    Items closest to the camera are the ones the viewer sees "on the outside"
    first for the current orientation; items farthest away are effectively
    "underneath" or "behind" other items from that viewing angle. Sorting this
    way lets the reveal slider peel off the nearest items first, regardless of
    which preset angle (Top, Front, Side, Isometric) is selected.
    """
    truck_w, truck_h, truck_d = truck_dims

    center_x = truck_w / 2.0
    center_y = truck_d / 2.0
    center_z = truck_h / 2.0

    eye_vec = (eye["x"], eye["y"], eye["z"])
    eye_len = math.sqrt(sum(c * c for c in eye_vec)) or 1.0

    # Gaze direction: points from the camera INTO the scene (opposite of eye vector).
    gaze = tuple(-c / eye_len for c in eye_vec)

    def depth_of(item: PackedItem) -> float:
        cx = item.x + item.w / 2.0
        cy = item.z + item.d / 2.0
        cz = item.y + item.h / 2.0

        rel_x = cx - center_x
        rel_y = cy - center_y
        rel_z = cz - center_z

        return rel_x * gaze[0] + rel_y * gaze[1] + rel_z * gaze[2]

    # Highest depth = farthest along the gaze direction = farthest from camera.
    return sorted(items, key=depth_of, reverse=True)

# --- VISUALIZATION ENGINE ---
def render_3d_packing_plot(
    items: list[PackedItem],
    truck_dims: tuple[float, float, float],
    camera_eye: dict = None
) -> go.Figure:
    if camera_eye is None:
        camera_eye = dict(x=1.7, y=-1.7, z=1.2)

    truck_w, truck_h, truck_d = truck_dims
    fig = go.Figure()
    rear_depth = truck_d * 0.08   # last 8% of truck

    fig.add_trace(
        go.Mesh3d(
            x=[0, truck_w, truck_w, 0],
            y=[truck_d - rear_depth, truck_d - rear_depth, truck_d, truck_d],
            z=[0, 0, 0, 0],
            i=[0, 0],
            j=[1, 2],
            k=[2, 3],
            color="red",
            opacity=0.35,
            hovertext="Rear Loading Door",
            hoverinfo="text",
            showscale=False
        )
    )
    truck_w, truck_h, truck_d = truck_dims

    for item in items:
        vx = [
            item.x,
            item.x + item.w,
            item.x + item.w,
            item.x,
            item.x,
            item.x + item.w,
            item.x + item.w,
            item.x
        ]

        vy = [
            item.z,
            item.z,
            item.z,
            item.z,
            item.z + item.d,
            item.z + item.d,
            item.z + item.d,
            item.z + item.d
        ]

        vz = [
            item.y,
            item.y,
            item.y + item.h,
            item.y + item.h,
            item.y,
            item.y,
            item.y + item.h,
            item.y + item.h
        ]
        i_cube = [7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2]
        j_cube = [3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3]
        k_cube = [0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6]

        hover_info = (
            f"<b>Item:</b> {item.name}<br>"
            f"<b>Weight:</b> {item.weight} kg<br>"
            f"<b>Max Load:</b> {item.max_load} kg<br>"
            f"<b>Dimensions:</b> {item.w}x{item.h}x{item.d} m"
        )

        fig.add_trace(go.Mesh3d(
            x=vx, y=vy, z=vz,
            i=i_cube, j=j_cube, k=k_cube,
            opacity=1.0,  
            flatshading=True,
            color=get_color(item.name),
            name=item.name,
            hoverinfo="text",
            text=hover_info
        ))
       
        x_lines = [
            item.x, item.x+item.w, None, item.x+item.w, item.x+item.w, None, item.x+item.w, item.x, None, item.x, item.x, None,
            item.x, item.x+item.w, None, item.x+item.w, item.x+item.w, None, item.x+item.w, item.x, None, item.x, item.x, None,
            item.x, item.x, None, item.x+item.w, item.x+item.w, None, item.x+item.w, item.x+item.w, None, item.x, item.x, None
        ]
        y_lines = [
            item.y, item.y, None, item.y, item.y+item.h, None, item.y+item.h, item.y+item.h, None, item.y+item.h, item.y, None,
            item.y, item.y, None, item.y, item.y+item.h, None, item.y+item.h, item.y+item.h, None, item.y+item.h, item.y, None,
            item.y, item.y, None, item.y, item.y, None, item.y+item.h, item.y+item.h, None, item.y+item.h, item.y+item.h, None
        ]
        z_lines = [
            item.z, item.z, None, item.z, item.z, None, item.z, item.z, None, item.z, item.z, None,
            item.z+item.d, item.z+item.d, None, item.z+item.d, item.z+item.d, None, item.z+item.d, item.z+item.d, None, item.z+item.d, item.z+item.d, None,
            item.z, item.z+item.d, None, item.z, item.z+item.d, None, item.z, item.z+item.d, None, item.z, item.z+item.d, None
        ]

        fig.add_trace(go.Scatter3d(
            x=x_lines, y=z_lines, z=y_lines,
            mode='lines', 
            line=dict(color='black', width=4), 
            showlegend=False,
            hoverinfo="skip"
        ))

    m = max(truck_w, truck_h, truck_d)

    x_ticks = generate_axis_ticks(truck_w)
    y_ticks = generate_axis_ticks(truck_d)
    z_ticks = generate_axis_ticks(truck_h)

    fig.update_layout(
        scene=dict(
            xaxis=dict(
                range=[0, truck_w], 
                title="Width", 
                tickmode="array",
                tickvals=x_ticks,
                ticktext=[f"{v:g}" for v in x_ticks],
                autorange=False, 
                showgrid=True, 
                zeroline=False
            ),
            yaxis=dict(
                range=[0, truck_d], 
                title="Depth", 
                tickmode="array",
                tickvals=y_ticks,
                ticktext=[f"{v:g}" for v in y_ticks],
                autorange=False, 
                showgrid=True, 
                zeroline=False
            ),
            zaxis=dict(
                range=[0, truck_h], 
                title="Height", 
                tickmode="array",
                tickvals=z_ticks,
                ticktext=[f"{v:g}" for v in z_ticks],
                autorange=False, 
                showgrid=True, 
                zeroline=False
            ),
            camera=dict(
                eye=camera_eye
            ),
            aspectmode="manual",
            aspectratio=dict(
                x=truck_w / m,
                y=truck_d / m,
                z=truck_h / m
            )
        ),  
        margin=dict(l=0, r=0, b=0, t=0)
    )
    return fig

def render_support_tree(graph: dict, node: str, level: int = 0):
    """Recursively prints the load-path tree in Streamlit."""
    indent = "&nbsp;" * 8 * level
    st.markdown(f"{indent}↳ **{node}**")
    for child in graph.get(node, []):
        render_support_tree(graph, child, level + 1)

# --- ISOLATED RERUN SCOPE FOR THE 3D VIEWER ---
@st.fragment
def render_packing_visual(bin_partno: str, packed_geometries: list[PackedItem], truck_dims: tuple[float, float, float]):
    """
    Fully client-side 3D packing viewer.

    Instead of driving the slider/orientation through Streamlit (which forces
    a server round-trip + fragment rerun on every change, causing the
    "release the mouse to see it update" lag), this builds ONE Plotly figure
    containing every item's traces and ships it to the browser once. The
    reveal slider, orientation dropdown, peel-order dropdown, and per-package
    visibility checkboxes are plain HTML controls that call
    Plotly.restyle()/Plotly.relayout() directly in JavaScript — so every
    single interaction updates the plot instantly, with zero Python calls.

    The viewer's light/dark theme automatically follows the host Streamlit
    app's theme (re-checked whenever Streamlit's theme changes), while the
    "Dark Mode" checkbox remains available as a manual override for the
    viewer only.
    """
    render_key = f"show_render_{bin_partno}"
    if render_key not in st.session_state:
        st.session_state[render_key] = False

    if st.button("Render 3D Packing Layout Matrix", key=f"render_plot_{bin_partno}"):
        st.session_state[render_key] = True
        st.session_state["dock1_pending_pipeline"] = bin_partno   # arm Dock 1 pipeline

    if not st.session_state[render_key]:
        return

    total_packed = len(packed_geometries)
    if total_packed == 0:
        st.info("No packages to display in the 3D view.")
        return

    truck_w, truck_h, truck_d = truck_dims

    camera_presets = {
        "Isometric": dict(x=1.7, y=-1.7, z=1.2),
        "Top":       dict(x=0.001, y=0.001, z=2.5),
        "Front":     dict(x=0.001, y=-2.5, z=0.001),
        "Side":      dict(x=2.5, y=0.001, z=0.001),
    }

    # Build ONE figure with every item included (all visible for now).
    fig = render_3d_packing_plot(packed_geometries, truck_dims, camera_eye=camera_presets["Isometric"])

    # Publish the EXACT figure rendered in the worker viewer to session state
    # so the Executive Digital Twin can extract it directly (no regeneration).
    # Keyed per-fleet (by bin part number) so each fleet's twin shows its own
    # layout, plus a global 'last_3d_figure' for backwards compatibility.
    st.session_state['last_3d_figure'] = fig
    st.session_state.setdefault('fleet_3d_figures', {})[bin_partno] = fig

    # --- Dock 1 pipeline trigger (one-shot, fires after the figure renders) ---
    # When the worker clicks "Render", this runs the full Dock 1 chain:
    # fleet upsert -> CCTV pairing -> Gemini analysis (with timeout fallback)
    # -> anomaly recording -> cross-view notification + toast.
    if st.session_state.get("dock1_pending_pipeline") == bin_partno:
        st.session_state["dock1_pending_pipeline"] = None
        with st.spinner("🛰️ Gemini spatial reasoning in progress…"):
            from services.dock_pipeline import run_dock1_render_pipeline
            run_dock1_render_pipeline(
                partno=bin_partno,
                fig=fig,
                manifest=st.session_state.get("manifest", []),
                packer=st.session_state.get("last_packer"),
                truck_w=truck_dims[0], truck_h=truck_dims[1], truck_d=truck_dims[2],
            )

    # Trace 0 = rear door. After that, each item contributes exactly 2 traces
    # in order: (mesh cube, edge lines) — matching render_3d_packing_plot's
    # add_trace order.
    item_trace_pairs = []
    idx = 1
    for item in packed_geometries:
        base_name = item.name.split("#")[0].strip()
        item_trace_pairs.append((idx, idx + 1, base_name))
        idx += 2
    total_traces = idx

    name_to_pair = {
        item.name: pair for item, pair in zip(packed_geometries, item_trace_pairs)
    }

    # Unique package types (by base name, e.g. "Blue Box") in first-seen order,
    # used to build the show/hide checklist. Defaults to every type visible.
    package_types = []
    seen_bases = set()
    for item in packed_geometries:
        base_name = item.name.split("#")[0].strip()
        if base_name not in seen_bases:
            seen_bases.add(base_name)
            package_types.append({"name": base_name, "color": get_color(base_name)})

    # Precompute farthest->closest ITEM order per camera preset, then map to
    # trace-index pairs (plus each item's base name, for the type filter).
    orderings = {}
    for preset_name, eye in camera_presets.items():
        ordered_items = sort_items_by_camera_depth(packed_geometries, eye, truck_dims)
        orderings[preset_name] = [list(name_to_pair[it.name]) for it in ordered_items]

    # Door-distance ordering: farthest-from-the-door items first, items
    # nearest the rear loading door last — so as the reveal slider is pulled
    # down, the boxes closest to the truck door disappear first.
    door_ordered = sorted(
        packed_geometries,
        key=lambda it: (it.z + it.d / 2.0)
    )
    orderings["__door__"] = [list(name_to_pair[it.name]) for it in door_ordered]

    fig_json = fig.to_plotly_json()
    fig_data_json = json.dumps(fig_json["data"])
    fig_layout_json = json.dumps(fig_json["layout"])
    orderings_json = json.dumps(orderings)
    camera_json = json.dumps(camera_presets)
    package_types_json = json.dumps(package_types)

    options_html = "".join(
        f'<option value="{name}"{" selected" if name == "Isometric" else ""}>{name}</option>'
        for name in camera_presets
    )

    package_toggle_html = "".join(
        '<label class="pkg-toggle-row" style="display:flex; align-items:center; gap:8px; margin:6px 0; cursor:pointer; font-size:0.9em;">'
        f'<input type="checkbox" class="pkg-toggle" data-base="{html_escape(pt["name"])}" checked>'
        f'<span style="display:inline-block; width:12px; height:12px; border-radius:3px; background:{pt["color"]}; flex-shrink:0;"></span>'
        f'<span class="pkg-toggle-label">{html_escape(pt["name"])}</span>'
        '</label>'
        for pt in package_types
    )

    html = f"""
    <style>
        #viewer_root_{bin_partno} {{ margin:0; font-family:sans-serif; color:#888; }}
        #viewer_root_{bin_partno} label, #viewer_root_{bin_partno} b,
        #viewer_root_{bin_partno} select, #viewer_root_{bin_partno} span {{ color:inherit; }}
        #viewer_root_{bin_partno} select {{ background:transparent; border:1px solid #8888; border-radius:4px; padding:4px; }}
        #pkg_list_{bin_partno} {{ max-height:180px; overflow-y:auto; margin-top:4px; }}
    </style>
    <div id="viewer_root_{bin_partno}" style="display:flex; gap:16px; align-items:flex-start;">
    <div id="plot_{bin_partno}" style="flex:4; height:640px; border-radius:6px; overflow:hidden;"></div>
    <div id="controls_{bin_partno}" style="flex:1; min-width:200px; padding:10px; border-radius:6px; transition: background-color 0.2s, color 0.2s;">
        <label for="orientation_{bin_partno}"><b>Viewer Orientation</b></label><br>
        <select id="orientation_{bin_partno}" style="width:100%; margin:6px 0 16px 0;">
        {options_html}
        </select>

        <label for="order_mode_{bin_partno}"><b>Peel Order</b></label><br>
        <select id="order_mode_{bin_partno}" style="width:100%; margin:6px 0 16px 0;">
            <option value="camera" selected>By Camera View</option>
            <option value="door">By Distance to Truck Door</option>
        </select>

        <label for="reveal_{bin_partno}"><b>Packages Visible</b></label><br>
            <input type="range" id="reveal_{bin_partno}" min="1" max="{total_packed}" value="{total_packed}" style="width:100%; margin-top:6px;">
            <div id="reveal_label_{bin_partno}" style="margin-top:4px; margin-bottom:16px; font-size:0.9em;">
                Showing {total_packed} of {total_packed} packages
            </div>

            <b>Show / Hide Package Types</b>
            <div id="pkg_list_{bin_partno}">
                {package_toggle_html}
            </div>

            <hr style="opacity:0.3; margin:16px 0;">

            <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
            <input type="checkbox" id="dark_{bin_partno}">
            <b>Dark Mode</b>
        </label>
        <div id="theme_auto_label_{bin_partno}" style="font-size:0.8em; margin-top:2px; opacity:0.75;"></div>
        <a href="#" id="theme_reset_{bin_partno}" style="font-size:0.8em; display:none; margin-top:2px;">Reset to app theme</a>
    </div>
    </div>
    <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
    <script>
        (function() {{
            const data = {fig_data_json};
            const layout = {fig_layout_json};
            const orderings = {orderings_json};
            const cameraPresets = {camera_json};
            const totalTraces = {total_traces};
            const totalPacked = {total_packed};

            const plotDiv = document.getElementById("plot_{bin_partno}");
            Plotly.newPlot(plotDiv, data, layout, {{responsive: true}});

            const orientationSel = document.getElementById("orientation_{bin_partno}");
            const orderModeSel   = document.getElementById("order_mode_{bin_partno}");
            const revealSlider   = document.getElementById("reveal_{bin_partno}");
            const revealLabel    = document.getElementById("reveal_label_{bin_partno}");
            const darkCheckbox   = document.getElementById("dark_{bin_partno}");
            const controlsPanel  = document.getElementById("controls_{bin_partno}");
            const autoLabel      = document.getElementById("theme_auto_label_{bin_partno}");
            const resetLink      = document.getElementById("theme_reset_{bin_partno}");
            const pkgToggles     = Array.prototype.slice.call(document.querySelectorAll("#pkg_list_{bin_partno} .pkg-toggle"));

            // Which package types (by base name) are currently shown. Defaults to all.
            const typeVisible = {{}};
            pkgToggles.forEach(function(cb) {{ typeVisible[cb.dataset.base] = true; }});

            // --- Visibility (cheap, WebGL-side toggle — no scene rebuild) ---
            // Combines the depth-reveal slider position with the peel-order
            // (camera-based or door-distance) and the per-type checkboxes.
            function computeVisible() {{
                const revealCount = parseInt(revealSlider.value, 10);
                const orderKey = orderModeSel.value === "door" ? "__door__" : orientationSel.value;
                const order = orderings[orderKey];
                const visible = new Array(totalTraces).fill(false);
                visible[0] = true; // rear door, always shown
                let shownCount = 0;
                for (let i = 0; i < order.length; i++) {{
                    const meshIdx = order[i][0];
                    const lineIdx = order[i][1];
                    const baseName = order[i][2];
                    const show = (i < revealCount) && (typeVisible[baseName] !== false);
                    if (show) shownCount++;
                    visible[meshIdx] = show;
                    visible[lineIdx] = show;
                }}
                return {{ visible: visible, shownCount: shownCount }};
            }}

            function updateLabel(shownCount) {{
                revealLabel.textContent = "Showing " + shownCount + " of " + totalPacked + " packages";
            }}

            // 'input' fires continuously while dragging — restyle only (batched
            // via requestAnimationFrame), so it stays smooth no matter how large
            // the manifest is.
            let rafPending = false;
            function applyRevealRAF() {{
                if (rafPending) return;
                rafPending = true;
                requestAnimationFrame(function() {{
                    const result = computeVisible();
                    Plotly.restyle(plotDiv, {{visible: result.visible}});
                    updateLabel(result.shownCount);
                    rafPending = false;
                }});
            }}

            // Orientation change: infrequent, so the heavier camera relayout is fine here.
            function applyOrientation() {{
                const result = computeVisible();
                Plotly.update(plotDiv, {{visible: result.visible}}, {{"scene.camera.eye": cameraPresets[orientationSel.value]}});
                updateLabel(result.shownCount);
            }}

            function applyOrderMode() {{
                const result = computeVisible();
                Plotly.restyle(plotDiv, {{visible: result.visible}});
                updateLabel(result.shownCount);
            }}

            function applyTypeToggle() {{
                const result = computeVisible();
                Plotly.restyle(plotDiv, {{visible: result.visible}});
                updateLabel(result.shownCount);
            }}

            // ---------------------------------------------------------------
            // Theme handling: follows the host Streamlit app's light/dark
            // theme automatically. The "Dark Mode" checkbox is a manual
            // override for this viewer only — flipping it stops the viewer
            // from auto-following until "Reset to app theme" is clicked.
            // ---------------------------------------------------------------
            const THEMES = {{
                dark:  {{ bg: "#111111", pane: "#1e1e1e", grid: "#3a3a3a", text: "#eeeeee", panelBg: "#1a1a1a", muted: "#aaaaaa", border: "#333333" }},
                light: {{ bg: "#ffffff", pane: "#ffffff", grid: "#dddddd", text: "#222222", panelBg: "#f4f4f4", muted: "#666666", border: "#e2e2e2" }}
            }};

            function detectHostIsDark() {{
                try {{
                    const doc = window.parent.document;
                    const el = doc.querySelector('[data-testid="stAppViewContainer"]') || doc.body;
                    const bg = window.parent.getComputedStyle(el).backgroundColor;
                    const m = bg.match(/\\d+/g);
                    if (m && m.length >= 3) {{
                        const r = Number(m[0]), g = Number(m[1]), b = Number(m[2]);
                        return (0.299 * r + 0.587 * g + 0.114 * b) < 128;
                    }}
                }} catch (e) {{
                    // Cross-origin / sandboxed iframe — fall through to OS preference.
                }}
                return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
            }}

            let manualOverride = false;

            function applyTheme(isDark) {{
                const t = isDark ? THEMES.dark : THEMES.light;

                document.body.style.backgroundColor = t.bg;
                document.body.style.color = t.text;

                Plotly.relayout(plotDiv, {{
                    paper_bgcolor: t.bg,
                    plot_bgcolor: t.bg,
                    "scene.xaxis.backgroundcolor": t.pane,
                    "scene.yaxis.backgroundcolor": t.pane,
                    "scene.zaxis.backgroundcolor": t.pane,
                    "scene.xaxis.gridcolor": t.grid,
                    "scene.yaxis.gridcolor": t.grid,
                    "scene.zaxis.gridcolor": t.grid,
                    "scene.xaxis.color": t.text,
                    "scene.yaxis.color": t.text,
                    "scene.zaxis.color": t.text,
                    font: {{ color: t.text }}
                }});

                controlsPanel.style.backgroundColor = t.panelBg;
                controlsPanel.style.color = t.text;
                controlsPanel.style.border = "1px solid " + t.border;
                revealLabel.style.color = t.muted;

                darkCheckbox.checked = isDark;
                autoLabel.textContent = manualOverride ? "Manual override" : "Following Streamlit theme";
                resetLink.style.display = manualOverride ? "inline-block" : "none";
            }}

            function syncTheme() {{
                if (manualOverride) return;
                applyTheme(detectHostIsDark());
            }}

            // Paint a theme-correct viewer immediately, before anything else,
            // so there is never a flash of default-colored (potentially
            // invisible) text.
            applyTheme(detectHostIsDark());

            darkCheckbox.addEventListener("change", function() {{
                manualOverride = true;
                applyTheme(darkCheckbox.checked);
            }});

            resetLink.addEventListener("click", function(e) {{
                e.preventDefault();
                manualOverride = false;
                syncTheme();
            }});

            // Stay in sync with Streamlit's theme (its own light/dark toggle,
            // or an OS-level scheme change) as long as the user hasn't
            // manually overridden the viewer.
            if (window.matchMedia) {{
                const mq = window.matchMedia("(prefers-color-scheme: dark)");
                const listen = mq.addEventListener ? mq.addEventListener.bind(mq) : mq.addListener.bind(mq);
                listen("change", syncTheme);
            }}
            try {{
                const parentDoc = window.parent.document;
                const observeTarget = parentDoc.querySelector('[data-testid="stAppViewContainer"]') || parentDoc.body;
                new MutationObserver(syncTheme).observe(observeTarget, {{attributes: true, attributeFilter: ["class", "style"]}});
                new MutationObserver(syncTheme).observe(parentDoc.documentElement, {{attributes: true, attributeFilter: ["class", "style"]}});
            }} catch (e) {{
                // Cross-origin sandbox — the matchMedia listener above still covers it.
            }}
            // Belt-and-braces fallback for setups where the observers above
            // can't attach: a cheap periodic check that only repaints when
            // the detected theme actually changes.
            let lastKnownDark = detectHostIsDark();
            setInterval(function() {{
                if (manualOverride) return;
                const nowDark = detectHostIsDark();
                if (nowDark !== lastKnownDark) {{
                    lastKnownDark = nowDark;
                    applyTheme(nowDark);
                }}
            }}, 1500);

            // --- Wire up controls ---
            revealSlider.addEventListener("input", applyRevealRAF);
            orientationSel.addEventListener("change", applyOrientation);
            orderModeSel.addEventListener("change", applyOrderMode);
            pkgToggles.forEach(function(cb) {{
                cb.addEventListener("change", function() {{
                    typeVisible[cb.dataset.base] = cb.checked;
                    applyTypeToggle();
                }});
            }});
        }})();
    </script>
    """

    components.html(html, height=680, scrolling=False)

# --- USER INTERFACE PRESENTATION LAYER ---
st.set_page_config(page_title="Axion Labs Fleet Optimizer", layout="wide", initial_sidebar_state="expanded")
st.title("Axion Labs: Fleet Space Optimization")

st.sidebar.header("1. Define Vehicle Space")
truck_w = st.sidebar.number_input("Truck Width (m)", value=2.4, step = 1.0)
truck_h = st.sidebar.number_input("Truck Height (m)", value=2.4, step = 1.0)
truck_d = st.sidebar.number_input("Truck Depth (m)", value=6.0, step = 1.0)
truck_weight = st.sidebar.number_input("Max Weight Capacity (kg)", value=4000)

st.sidebar.header("2. Import Cargo Manifest")
uploaded_file = st.sidebar.file_uploader(
    "Upload Excel Manifest",
    type=["xlsx"],
    help="Upload an .xlsx cargo manifest using the expected column names."
)
import_manifest = st.sidebar.button(
    "Import Manifest"
)

st.sidebar.header("Or")

st.sidebar.header("2. Add Cargo Item Manually")
item_name = st.sidebar.text_input("Item Name", value="Generic Box")
item_w = st.sidebar.number_input("Item Width (cm)", value=8.0, step = 0.1)
item_h = st.sidebar.number_input("Item Height (cm)", value=8.0, step = 0.1)
item_d = st.sidebar.number_input("Item Depth (cm)", value=8.0, step = 0.1)
item_weight = st.sidebar.number_input("Item Weight (kg)", value=15)

# --- CONSTANTS & CONFIGURATION ---
max_supported_load = st.sidebar.number_input(
    "Maximum Supported Load (kg)",
    min_value=0.0,
    value=50.0,
)

quantity = st.sidebar.number_input("Quantity", min_value=1, value=1, step=1)
unloading_sequence = st.sidebar.number_input(
    "Unloading Sequence",
    min_value=1,
    value=1,
    step=1,
    help=(
        "Controls where this cargo ends up in the truck, not just how it's scored. "
        "Sequence 1 = unloaded first, so it gets packed last and placed nearest the door. "
        "Higher numbers get packed earlier and end up deeper in the truck. "
        "Items are grouped into broad zones by sequence; within a zone, weight limit and size still decide the exact fit."
    )
)
st.sidebar.caption(
    "💡 Lower sequence number = unloaded first = placed closer to the truck door."
)

add_item = st.sidebar.button("Add Item to Manifest")

if 'manifest' not in st.session_state:
    st.session_state.manifest = []

if "editing_orientation" not in st.session_state:
    st.session_state.editing_orientation = None

if "import_queue" not in st.session_state:
    st.session_state.import_queue = []

if "importing_manifest" not in st.session_state:
    st.session_state.importing_manifest = False

if import_manifest and uploaded_file is not None:

    try:
        df = pd.read_excel(uploaded_file)

        required_columns = [
            "Item Description",
            "Box Quantity",
            "Box Weight (kg)",
            "Length (cm)",
            "Width (cm)",
            "Height (cm)",
            "Fragile",
            "Unloading Sequence"
        ]

        missing_columns = [
            column
            for column in required_columns
            if column not in df.columns
        ]

        if missing_columns:

            st.sidebar.error(
                "Missing required columns: "
                + ", ".join(missing_columns)
            )

        else:

            imported_items = []

            for _, row in df.iterrows():

                fragile_value = str(row["Fragile"]).strip().lower()

                is_fragile = fragile_value in {
                    "yes",
                    "y",
                    "true",
                    "1"
                }

                imported_items.append({

                    "name": str(row["Item Description"]),

                    "width": float(row["Width (cm)"]) / 100,

                    "height": float(row["Height (cm)"]) / 100,

                    "depth": float(row["Length (cm)"]) / 100,

                    "weight": float(row["Box Weight (kg)"]),

                    "quantity": int(row["Box Quantity"]),

                    "max_load": (
                        float(row["Box Weight (kg)"])
                        if is_fragile
                        else float("inf")
                    ),

                    "sequence": int(row["Unloading Sequence"])

                })

            st.session_state.import_queue = imported_items
            st.session_state.importing_manifest = True

            st.success(
                f"Successfully imported {len(imported_items)} cargo types."
            )

            st.rerun()

    except Exception as e:

        st.sidebar.error(
            f"Could not read the Excel file: {e}"
        )

if add_item:

    if any(item["name"] == item_name for item in st.session_state.manifest):
        st.sidebar.error("Package name already exists!")

    else:
        st.session_state.editing_orientation = {

                "name": item_name,
                "width": item_w / 100,  # Convert cm to m
                "height": item_h / 100,  # Convert cm to m
                "depth": item_d / 100,  # Convert cm to m
                "weight": item_weight,
                
                "quantity": quantity,
                "max_load": max_supported_load,
                "sequence": unloading_sequence
            }
        st.rerun()

if "name_reverts" not in st.session_state:
    st.session_state.name_reverts = {}
if "pending_warning" not in st.session_state:
    st.session_state.pending_warning = None

for idx, old_name in st.session_state.name_reverts.items():
    st.session_state[f"name_{idx}"] = old_name   # safe: widget hasn't run yet this pass
st.session_state.name_reverts = {}

if st.session_state.pending_warning:
    st.warning(st.session_state.pending_warning)
    st.session_state.pending_warning = None

st.subheader("Current Cargo Manifest")
if not st.session_state.manifest:
    st.info("No cargo has been added yet.")
else:
    # Header row (fake labels, since the widgets below hide their own labels)
    h1, h2, h3, h4, h5, h6, h7, h8 = st.columns([2, 1, 1, 1, 1, 1, 1, 0.6])
    h1.markdown("**Name**")
    h2.markdown("**Width (m)**")
    h3.markdown("**Height (m)**")
    h4.markdown("**Depth (m)**")
    h5.markdown("**Weight**")
    h6.markdown("**Qty**")
    h7.markdown("**Seq**")
    st.caption("Seq = unloading order. 1 unloads first and lands nearest the truck door; higher numbers unload later and pack deeper inside.")

    for i, cargo in enumerate(st.session_state.manifest):
        c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([2, 1, 1, 1, 1, 1, 1, 0.6])

        new_name = c1.text_input(
            "Name", value=cargo["name"], key=f"name_{i}", label_visibility="collapsed"
        )

        if new_name != cargo["name"]:
            is_duplicate = any(
                other_i != i and other["name"] == new_name
                for other_i, other in enumerate(st.session_state.manifest)
            )
            if is_duplicate:
                st.session_state.pending_warning = f"'{new_name}' already exists. Reverted to '{cargo['name']}'."
                st.session_state.name_reverts[i] = cargo["name"]
                st.rerun()
            else:
                cargo["name"] = new_name

        cargo["w"] = c2.number_input(
            "W", value=float(cargo["w"]), step=0.1, key=f"w_{i}", label_visibility="collapsed"
        )
        cargo["h"] = c3.number_input(
            "H", value=float(cargo["h"]), step=0.1, key=f"h_{i}", label_visibility="collapsed"
        )
        cargo["d"] = c4.number_input(
            "D", value=float(cargo["d"]), step=0.1, key=f"d_{i}", label_visibility="collapsed"
        )
        cargo["weight"] = c5.number_input(
            "Weight", value=float(cargo["weight"]), key=f"weight_{i}", label_visibility="collapsed"
        )
        cargo["quantity"] = c6.number_input(
            "Qty", value=int(cargo["quantity"]), min_value=1, step=1, key=f"qty_{i}", label_visibility="collapsed"
        )
        cargo["sequence"] = c7.number_input(
            "Seq", value=int(cargo["sequence"]), min_value=1, step=1, key=f"seq_{i}", label_visibility="collapsed",
            help="Unloading order: 1 unloads first (packed last, nearest the door). Higher = unloads later (packed earlier, deeper in truck)."
        )

        if c8.button("🗑️", key=f"delete_{i}"):
            st.session_state.manifest.pop(i)
            st.rerun()


# --------------------------------------------------
# Orientation Editor
# --------------------------------------------------

if (
    st.session_state.importing_manifest
    and st.session_state.editing_orientation is None
    and st.session_state.import_queue
):

    st.session_state.editing_orientation = (
        st.session_state.import_queue.pop(0)
    )

    st.rerun()


if st.session_state.editing_orientation is not None:

    result = launch_orientation_editor(
        **st.session_state.editing_orientation
    )

    if result is None:

        # User cancelled this cargo item
        st.session_state.editing_orientation = None

        if not st.session_state.import_queue:

            st.session_state.importing_manifest = False

        st.rerun()

    elif result != "WAITING":

        # Orientation has been selected
        st.session_state.manifest.append(result)

        st.session_state.editing_orientation = None

        # More imported cargo remains
        if st.session_state.import_queue:

            st.rerun()

        else:

            # Import finished
            st.session_state.importing_manifest = False

            st.success("✅ Entire manifest imported and oriented.")

            st.rerun()

    st.stop()

# --- RUN EXECUTION SOLVER ---
prioritize_sequence = st.checkbox(
    "Prioritize unloading sequence over space efficiency",
    value=False,
    help=(
        "Off (default): packs for maximum space usage. Sequence still breaks ties "
        "between identical-size, identical-weight-limit items, but otherwise doesn't "
        "influence placement. On: groups cargo into rough front/door zones by sequence "
        "first - this can leave more empty space in the truck, so check the Space "
        "Volume Utilization score after running."
    )
)
if st.button("Run AI Optimization"):
    if not st.session_state.manifest:
        st.error("Your cargo manifest is completely empty!")
    else:
        all_layouts = []
        invalid_items = validate_cargo_dimensions(
            st.session_state.manifest
        )

        if invalid_items:

            st.error("Cannot generate layout because some cargo dimensions are invalid.")

            for error in invalid_items:
                st.error(error)

            st.stop()

        loading_order = build_loading_priority(
            st.session_state.manifest
        )

        # py3dbp re-sorts every item internally right before packing, by
        # level -> loadbear -> volume, and that internal sort (not the
        # order we add items in) is what actually decides placement.
        # This is a greedy "first-fit against already-placed items"
        # algorithm (see pack2Bin) with no lookahead or backtracking, so
        # it's highly sensitive to item order - the loadbear-descending /
        # volume-ascending order it uses by default is what keeps the
        # pack space-efficient.
        #
        # Forcing sequence into `level` (tried previously) overrides that
        # order and reliably costs space efficiency, in ways that are hard
        # to predict from the code alone. So by default we leave level=1
        # for everyone - identical to pre-sequence-feature behavior, zero
        # efficiency risk. Sequence still acts as a free tie-break: items
        # that end up with identical loadbear AND identical volume keep
        # the sequence-sorted order they arrived in (build_loading_priority
        # sorts loading_order by -sequence first), with no downside since
        # that only ever resolves ties that would otherwise be arbitrary.
        #
        # Only when the user explicitly opts in (accepting the efficiency
        # trade-off) do we bucket sequence into 2 coarse zones via level,
        # to more directly bias which half of the truck cargo ends up in.
        max_sequence = max(
            (obj["sequence"] for obj in loading_order),
            default=1
        )

        if prioritize_sequence:
            NUM_TIERS = 2
            tier_size = max(1, -(-max_sequence // NUM_TIERS))  # ceil division

            def sequence_to_level(sequence):
                bucket = -(-sequence // tier_size)      # 1..NUM_TIERS, low seq -> low bucket
                return NUM_TIERS - bucket + 1            # invert: low seq -> high level (packed last)
        else:
            def sequence_to_level(sequence):
                return 1

        packer = Packer()

        packer.addBin(
                Bin(
                    "Truck",
                    (
                        truck_w * 100,
                        truck_h * 100,
                        truck_d * 100
                      ),
                    truck_weight
                )
            )

        counter = 0

        for obj in loading_order:

                for i in range(obj["quantity"]):

                    packer.addItem(

                        Item(

                            partno=f"ITEM-{counter}",

                            name=f'{obj["name"]} #{i+1}',

                            typeof="cube",

                            WHD=(
                                float(obj["w"]) * 100,
                                float(obj["h"]) * 100,
                                float(obj["d"]) * 100
                            ),

                            weight=obj["weight"],

                            # Bucket sequence into 3 coarse tiers (matching
                            # py3dbp's documented level range) so loadbear/
                            # volume still drives fit within each tier.
                            level=sequence_to_level(obj["sequence"]),

                            loadbear=obj["max_load"],

                            updown=False,

                            color=get_color(obj["name"])

                        )

                    )

                    counter += 1

        packer.pack(

                bigger_first=False,

                fix_point=True,

                check_stable=True,

                support_surface_ratio=0.45,

                number_of_decimals=3 

            )

        packer.putOrder()

        packed_geometries = []

        manifest_lookup = {

                f"{item['name']} #{i+1}": item

                for item in st.session_state.manifest

                for i in range(item["quantity"])

            }

        for b in packer.bins:

                for item in b.items:

                    m = manifest_lookup[item.name]

                    pos = item.position

                    dim = item.getDimension()

                    packed_geometries.append(

                        PackedItem(

                            name=item.name,

                            x=float(pos[0]) / 100,
                            y=float(pos[1]) / 100,
                            z=float(pos[2]) / 100,

                            w=float(dim[0]) / 100,
                            h=float(dim[1]) / 100,
                            d=float(dim[2]) / 100,

                            weight=float(item.weight),

                            max_load=m["max_load"]

                        )

                    )

        utilization = calculate_utilization(
                packed_geometries,
                float(truck_w * truck_h * truck_d)
            )

        load_distribution, _ = calculate_load_distribution(
                packed_geometries
            )

        safe_count = sum(
                1
                for item in packed_geometries
                if load_distribution[item.name] <= item.max_load
            )

        safety_rate = (
                safe_count / len(packed_geometries) * 100
                if packed_geometries else 0
            )

        offloading_score = calculate_offloading_score(
                packed_geometries,
                manifest_lookup
            )

        overall_score = (
                utilization * 0.4
                + safety_rate * 0.4
                + offloading_score * 0.2
            )

        all_layouts.append({

                "packer": packer,

                "packed": packed_geometries,

                "utilization": utilization,

                "safety": safety_rate,

                "offloading": offloading_score,

                "overall": overall_score
            })

        if len(all_layouts) == 0:

            st.error("No layout generated.")

        else:
            all_layouts.sort(
                key=lambda x: x["overall"],
                reverse=True
            )

            st.session_state.layouts = all_layouts
            best_layout = all_layouts[0]

            st.session_state.last_packer = best_layout["packer"]

            # --- Register fleet in View 2 (Executive Control Tower) ---
            # Auto-register this packing result as an active fleet
            register_fleet_from_packing_result(
                manifest=st.session_state.manifest,
                packer=st.session_state.last_packer,
                truck_w=truck_w,
                truck_h=truck_h,
                truck_d=truck_d,
                truck_name=f"Truck-{len(st.session_state.get('active_fleets', [])) + 1}",
            )

# --- VISUALIZATION AND REPORTING OUTPUT LAYER ---
if 'last_packer' in st.session_state:
    packer = st.session_state.last_packer
    manifest_lookup = {f"{item['name']} #{i+1}": item for item in st.session_state.manifest for i in range(item["quantity"])}
    truck_vol = float(truck_w * truck_h * truck_d)
   
    for b in packer.bins:
        st.markdown("---")
        st.subheader(f"Optimal Layout Assignment: Compartment Box ({b.partno})")
        
        packed_geometries = []
        for item in b.items:
            m_data = manifest_lookup.get(item.name)
            if m_data is None:
                continue

            pos, dim = item.position, item.getDimension()

            packed_geometries.append(
                PackedItem(
                    name=item.name,

                    # py3dbp uses centimeters → convert back to meters
                    x=float(pos[0]) / 100,
                    y=float(pos[1]) / 100,
                    z=float(pos[2]) / 100,

                    w=float(dim[0]) / 100,
                    h=float(dim[1]) / 100,
                    d=float(dim[2]) / 100,

                    weight=float(item.weight),

                    max_load=m_data["max_load"]
                )
            )

        utilization_rate = calculate_utilization(packed_geometries, truck_vol)
        load_distribution, support_graph = calculate_load_distribution(packed_geometries)
        offloading_score = calculate_offloading_score(
            packed_geometries,
            manifest_lookup
        )
        
        safe_count = sum(1 for item in packed_geometries if load_distribution[item.name] <= item.max_load)
        safety_rate = (safe_count / len(packed_geometries) * 100) if packed_geometries else 100.0

        safety_stars, safety_text = score_to_stars(
            safety_rate
        )
        offloading_stars, offloading_text = score_to_stars(
            offloading_score
        )
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            total_items = sum(x["quantity"] for x in st.session_state.manifest)
            st.metric("Total Packed Count", f"{len(packed_geometries)} / {total_items}")
        with col2:
            st.metric("Space Volume Utilization", f"{utilization_rate:.1f}%")
        with col3:
            st.metric("Structural Safety Score", safety_stars)
            st.caption(safety_text)
        with col4:
            st.metric(
                "Offloading Score",
                offloading_stars
            )
            st.caption(offloading_text)
        if prioritize_sequence:
            st.caption(
                "ℹ️ Packed with sequence prioritized over space efficiency. "
                "Compare Space Volume Utilization against a run with the checkbox off "
                "to see the trade-off."
            )
        unfitted = getattr(b, 'unfitted_items', [])
        if unfitted:
            st.subheader("⚠️ Unpacked Items (Rejected By Constraints)")
            for item in unfitted:
                st.error(f"**{item.name}** could not be packed securely. Adjust dimensions or stack settings.")

        # --------------------------------------------------
        # 3D Render + Depth-Reveal Slider (isolated fragment)
        # --------------------------------------------------
        render_packing_visual(b.partno, packed_geometries, (truck_w, truck_h, truck_d))

#end