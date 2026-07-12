#app.py
import streamlit as st
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
from dataclasses import dataclass
from orientation_editor import launch_orientation_editor

# --- CONSTANTS & CONFIGURATION ---
LOAD_LIMITS = {
    "Normal": float("inf"),
    "Medium": 80.0,
    "Fragile": 30.0,
    "Extremely Fragile": 10.0
}

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
    fragility: str
    limit: float

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

def calculate_utilization(items: list[PackedItem], truck_volume: float) -> float:
    if truck_volume <= 0:
        return 0.0
    used_volume = sum((item.w * item.h * item.d) for item in items)
    return (used_volume / truck_volume) * 100

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
            item["load_limit"],

            # larger volume first
            -(item["w"] * item["h"] * item["d"]),

            # heavier first
            -item["weight"]

        )
    )

# --- VISUALIZATION ENGINE ---
def render_3d_packing_plot(items: list[PackedItem], truck_dims: tuple[float, float, float]) -> go.Figure:
    truck_w, truck_h, truck_d = truck_dims
    fig = go.Figure()
    rear_depth = truck_d * 0.08   # last 8% of truck

    fig.add_trace(
        go.Mesh3d(
            x=[
                0, truck_w, truck_w, 0
            ],
            y=[
                0, 0, 0, 0
            ],
            z=[
                truck_d - rear_depth,
                truck_d - rear_depth,
                truck_d,
                truck_d
            ],
            i=[0,0],
            j=[1,2],
            k=[2,3],
            color="red",
            opacity=0.35,
            hovertext="Rear Loading Door",
            hoverinfo="text",
            showscale=False
        )#YEA FIX THIS ONE FOR SURE MAN
    )
    truck_w, truck_h, truck_d = truck_dims

    for item in items:
        vx = [item.x, item.x+item.w, item.x+item.w, item.x, item.x, item.x+item.w, item.x+item.w, item.x]
        vy = [item.y, item.y, item.y+item.h, item.y+item.h, item.y, item.y, item.y+item.h, item.y+item.h]
        vz = [item.z, item.z, item.z, item.z, item.z+item.d, item.z+item.d, item.z+item.d, item.z+item.d]

        i_cube = [7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2]
        j_cube = [3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3]
        k_cube = [0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6]

        hover_info = (
            f"<b>Item:</b> {item.name}<br>"
            f"<b>Weight:</b> {item.weight} kg<br>"
            f"<b>Fragility:</b> {item.fragility}<br>"
            f"<b>Dimensions:</b> {item.w}x{item.h}x{item.d} cm"
        )

        fig.add_trace(go.Mesh3d(
            x=vx, y=vy, z=vz,
            i=i_cube, j=j_cube, k=k_cube,
            opacity=0.85,  
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
            x=x_lines, y=y_lines, z=z_lines,
            mode='lines', 
            line=dict(color='black', width=4), 
            showlegend=False,
            hoverinfo="skip"
        ))

    m = max(truck_w, truck_h, truck_d)

    fig.update_layout(
        scene=dict(
            xaxis=dict(range=[0, truck_w], title="Width"),
            yaxis=dict(range=[0, truck_h], title="Depth"),
            zaxis=dict(range=[0, truck_d], title="Height"),

            aspectmode="manual",
            aspectratio=dict(
                x=truck_w / m,
                y=truck_h / m,
                z=truck_d / m
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

# --- USER INTERFACE PRESENTATION LAYER ---
st.set_page_config(page_title="Axion Labs Fleet Optimizer", layout="wide")
st.title("Axion Labs: Fleet Space Optimization")

st.sidebar.header("1. Define Vehicle Space")
truck_w = st.sidebar.number_input("Truck Width (cm)", value=600)
truck_h = st.sidebar.number_input("Truck Depth (cm)", value=600)
truck_d = st.sidebar.number_input("Truck Height (cm)", value=600)
truck_weight = st.sidebar.number_input("Max Weight Capacity (kg)", value=4000)

st.sidebar.header("2. Add Cargo Item")
item_name = st.sidebar.text_input("Item Name", value="Generic Box")
item_w = st.sidebar.number_input("Item Width", value=200)
item_h = st.sidebar.number_input("Item Height", value=200)
item_d = st.sidebar.number_input("Item Depth", value=200)
item_weight = st.sidebar.number_input("Item Weight (kg)", value=15)
quantity = st.sidebar.number_input("Quantity", min_value=1, value=1, step=1)
unloading_sequence = st.sidebar.number_input(
    "Unloading Sequence",
    min_value=1,
    value=1,
    step=1
)
fragility = st.sidebar.selectbox("Fragility Level", list(LOAD_LIMITS.keys()))
add_item = st.sidebar.button("Add Item to Manifest")

if 'manifest' not in st.session_state:
    st.session_state.manifest = []
if "editing_orientation" not in st.session_state:
    st.session_state.editing_orientation = None

if add_item:

    if any(item["name"] == item_name for item in st.session_state.manifest):
        st.sidebar.error("Package name already exists!")

    else:
        st.session_state.editing_orientation = {

                "name": item_name,
                "width": item_w,
                "height": item_h,
                "depth": item_d,
                "weight": item_weight,
                "fragility": fragility,
                "quantity": quantity,
                "load_limit": LOAD_LIMITS[fragility],
                "sequence": unloading_sequence
            }
        st.rerun()
        st.write(st.session_state.manifest)

st.subheader("Current Cargo Manifest")
st.write(st.session_state.manifest)

# --------------------------------------------------
# Orientation Editor Popup
# --------------------------------------------------

if st.session_state.editing_orientation is not None:

    result = launch_orientation_editor(
        **st.session_state.editing_orientation
    )

    if result is None:
        # User cancelled
        st.session_state.editing_orientation = None
        st.rerun()

    elif result != "WAITING":
        # User confirmed orientation
        result["orientation"] = False   # rotation already fixed

        st.session_state.manifest.append(result)

        st.session_state.editing_orientation = None

        st.success(f"Added {result['name']}!")

        st.rerun()

    st.stop()

# --- RUN EXECUTION SOLVER ---
if st.button("🚀 Run AI Optimization"):
    if not st.session_state.manifest:
        st.error("Your cargo manifest is completely empty!")
    else:
        packer = Packer()
        packer.addBin(Bin('Truck', (truck_w, truck_h, truck_d), truck_weight))
       
        loading_order = build_loading_priority(
            st.session_state.manifest
        )

        counter = 0

        for obj in loading_order:
            for i in range(obj["quantity"]):
                packer.addItem(Item(
                    partno=f"ITEM-{counter}",
                    name=f'{obj["name"]} #{i+1}',
                    typeof='cube',
                    WHD=(obj["w"], obj["h"], obj["d"]),
                    weight=obj["weight"],
                    level=1,
                    loadbear=obj["load_limit"],
                    updown=obj["orientation"],
                    color=get_color(obj["name"])
                ))
                counter += 1

        with st.spinner("Calculating Realistic Layout Matrix..."):
            packer.pack(
                bigger_first=True,
                fix_point=True,      
                check_stable=True,   
                support_surface_ratio=0.75 
            )
            packer.putOrder()
            st.session_state.last_packer = packer

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
            packed_geometries.append(PackedItem(
                name=item.name,
                x=float(pos[0]), y=float(pos[1]), z=float(pos[2]),
                w=float(dim[0]), h=float(dim[1]), d=float(dim[2]),
                weight=float(item.weight),
                fragility=m_data["fragility"],
                limit=m_data["load_limit"] 
            ))
            
        utilization_rate = calculate_utilization(packed_geometries, truck_vol)
        load_distribution, support_graph = calculate_load_distribution(packed_geometries)
        offloading_score = calculate_offloading_score(
            packed_geometries,
            manifest_lookup
        )
        
        safe_count = sum(1 for item in packed_geometries if load_distribution[item.name] <= item.limit)
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
            st.metric("Total Packed Count", f"{len(b.items)} / {total_items}")
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
        unfitted = getattr(b, 'unfitted_items', [])
        if unfitted:
            st.subheader("⚠️ Unpacked Items (Rejected By Constraints)")
            for item in unfitted:
                st.error(f"**{item.name}** could not be packed securely. Adjust dimensions or stack settings.")
                
        #col_report, col_graph = st.columns(2)
        
        #with col_report:
            #st.subheader("Structural Load Distribution Analysis")
            #for item in packed_geometries:
                #current_load = load_distribution[item.name]
                #if current_load <= item.limit:
                    #st.success(f"✅ **{item.name}** | Capacity: {current_load:.1f} kg / {item.limit} kg")
                #else:
                    #st.error(f"⚠️ **{item.name}** OVERLOADED | Capacity: {current_load:.1f} kg / {item.limit} kg")

        #with col_graph:
            #st.subheader("Structural Support Chain (Load Path)")
            #base_items = [item.name for item in packed_geometries if item.y == 0.0]
            #if not base_items:
                #st.write("No items packed.")
            #for base in base_items:
                #render_support_tree(support_graph, base)

        if st.button("📊 Render 3D Packing Layout Matrix", key=f"render_plot_{b.partno}"):
            with st.spinner("Building interactive scene graph..."):
                fig = render_3d_packing_plot(packed_geometries, (truck_w, truck_h, truck_d))
                st.plotly_chart(fig, use_container_width=True)