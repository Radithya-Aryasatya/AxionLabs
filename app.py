import streamlit as st
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
import hashlib

# --- HALO ARKAN, ARYA, AXEL TUNG TUNG ---
# - Mari kita menangkan lomba ini! SemangaTT -


# --- UI Setup ---
st.set_page_config(page_title="Axion Labs Fleet Optimizer", layout="wide")
st.title("Axion Labs: Fleet Space Optimization")

# --- Sidebar Inputs (User Controls) ---
st.sidebar.header("1. Define Vehicle Space")
truck_w = st.sidebar.number_input("Truck Width (cm)", value=600)
truck_h = st.sidebar.number_input("Truck Height (cm)", value=260)
truck_d = st.sidebar.number_input("Truck Depth (cm)", value=240)
truck_weight = st.sidebar.number_input("Max Weight Capacity (kg)", value=4000)

st.sidebar.header("2. Add Cargo Item")
item_name = st.sidebar.text_input("Item Name", value="Generic Box")
item_w = st.sidebar.number_input("Item Width", value=50)
item_h = st.sidebar.number_input("Item Height", value=50)
item_d = st.sidebar.number_input("Item Depth", value=50)
item_weight = st.sidebar.number_input("Item Weight (kg)", value=10)
fragility = st.sidebar.selectbox(
    "Fragility Level",
    [
        "Normal",
        "Medium",
        "Fragile",
        "Extremely Fragile"
    ]
)
add_item = st.sidebar.button("Add Item to Manifest")

# --- Session State (Memory for the web app) ---
if 'manifest' not in st.session_state:
    st.session_state.manifest = []

if add_item:
    st.session_state.manifest.append({
        "name": item_name, "w": item_w, "h": item_h, "d": item_d, "weight": item_weight, "fragility": fragility
    })
    st.sidebar.success(f"Added {item_name}!")

# --- Main Dashboard ---
st.subheader("Current Cargo Manifest")
st.write(st.session_state.manifest)

if st.button("🚀 Run AI Optimization"):
    packer = Packer()
    # Add the truck
    packer.addBin(Bin('Truck', (truck_w, truck_h, truck_d), truck_weight))
    
    # Add all items from the user's list
    for idx, obj in enumerate(st.session_state.manifest):
        packer.addItem(Item(
            partno=f"ITEM-{idx}", 
            name=obj["name"], 
            typeof='cube', 
            WHD=(obj["w"], obj["h"], obj["d"]), 
            weight=obj["weight"], 
            level=1, loadbear=100, updown=True, color='blue'
        ))
    
    # Run the math
    with st.spinner("Calculating optimal layout..."):
        packer.pack(bigger_first=True, fix_point=True, check_stable=True, support_surface_ratio=0.75)
        packer.putOrder()
        # Save results to session state so they persist
        st.session_state.last_packer = packer
        st.success("Optimization Complete!")

# --- Display Results ---
if 'last_packer' in st.session_state:
    packer = st.session_state.last_packer
    for b in packer.bins:
        st.write(f"**Vehicle Used:** {b.partno}")
        st.write(f"**Total Items Packed:** {len(b.items)}")
        
        # Fragility validation
        fragility_report = []
        for item in b.items:
            # Search data in manifest
            item_data = next(
                x for x in st.session_state.manifest
                if x["name"] == item.name
            )
            fragility = item_data["fragility"]
            
            if item_data["fragility"] == "Normal":
                continue
        
            pos = item.position
            dim = item.getDimension()
            top = float(pos[2]) + float(dim[1])
            overloaded = False
        
            for other in b.items:
                if other == item:
                    continue
                opos = other.position
                if float(opos[2]) >= top:
                    overloaded = True
                    break
                
        
            fragility_report.append({
                "name": item.name,
                "safe": not overloaded
            })

        # Counting Safety Rate
        safe = sum(r["safe"] for r in fragility_report)

        if len(fragility_report) > 0:
            rate = safe / len(fragility_report) * 100
        else:
            rate = 100

        # Show Metric
        st.metric(
            "Fragility Safety Rate",
            f"{rate:.1f}%"
        )
        
        # 1. Show coordinates list
        for item in b.items:
            pos = item.position
            x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
    
            # Explicitly convert dimensions to float here
            dim = item.getDimension()
            w, h, d = float(dim[0]), float(dim[1]), float(dim[2])
    
            x_coords = [x, x+w, x+w, x, x, x+w, x+w, x]
            y_coords = [y, y, y+d, y+d, y, y, y+d, y+d]
            z_coords = [z, z, z, z, z+h, z+h, z+h, z+h]

        # 2. Single Visualization Button
        if st.button("📊 Visualize Packing Layout"):
            fig = go.Figure()

            # --- Function for consistent colors ---
            def get_color(level):
                colors = {
                    "Normal": "green",
                    "Medium": "yellow",
                    "Fragile": "orange",
                    "Extremely Fragile": "red"
                }

                return colors[level]

            # Draw the Truck container (Wireframe)
            tw, th, td = float(truck_w), float(truck_h), float(truck_d)
            fig.add_trace(go.Mesh3d(
                x=[0, tw, tw, 0, 0, tw, tw, 0],
                y=[0, 0, td, td, 0, 0, td, td],
                z=[0, 0, 0, 0, th, th, th, th],
                opacity=0.1, color='cyan', name='Truck'
            ))

            # Add each packed item
            for item in b.items:
                pos = item.position
                x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
                
                dim = item.getDimension() # Use underscore version
                w, h, d = float(dim[0]), float(dim[1]), float(dim[2])
                
                # 8 corners
                x_c = [x, x+w, x+w, x, x, x+w, x+w, x]
                y_c = [y, y, y+d, y+d, y, y, y+d, y+d]
                z_c = [z, z, z, z, z+h, z+h, z+h, z+h]
                
                # Face indices
                i = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4]
                j = [1, 2, 4, 5, 2, 6, 3, 7, 0, 4, 5, 6]
                k = [2, 3, 5, 6, 6, 2, 7, 3, 4, 0, 6, 5]

                # 1. Add the solid Mesh (the box body)
                fig.add_trace(go.Mesh3d(
                    x = x_c,
                    y = y_c,
                    z = z_c,
                    i = i,
                    j = j,   
                    k = k,
                    opacity = 0.6,
                    color = get_color(fragility),
                    name = item.name
                ))
                
                # 2. Add the wireframe lines (the outlines)
                # These are the connections between the 8 corners
                edge_x = [x_c[0], x_c[1], x_c[1], x_c[2], x_c[2], x_c[3], x_c[3], x_c[0], x_c[4], x_c[5], x_c[5], x_c[6], x_c[6], x_c[7], x_c[7], x_c[4], x_c[0], x_c[4], x_c[1], x_c[5], x_c[2], x_c[6], x_c[3], x_c[7]]
                edge_y = [y_c[0], y_c[1], y_c[1], y_c[2], y_c[2], y_c[3], y_c[3], y_c[0], y_c[4], y_c[5], y_c[5], y_c[6], y_c[6], y_c[7], y_c[7], y_c[4], y_c[0], y_c[4], y_c[1], y_c[5], y_c[2], y_c[6], y_c[3], y_c[7]]
                edge_z = [z_c[0], z_c[1], z_c[1], z_c[2], z_c[2], z_c[3], z_c[3], z_c[0], z_c[4], z_c[5], z_c[5], z_c[6], z_c[6], z_c[7], z_c[7], z_c[4], z_c[0], z_c[4], z_c[1], z_c[5], z_c[2], z_c[6], z_c[3], z_c[7]]

                fig.add_trace(go.Scatter3d(
                    x=edge_x, y=edge_y, z=edge_z,
                    mode='lines',
                    line=dict(color='black', width=4),
                    showlegend=False
                ))

            fig.update_layout(scene=dict(
                xaxis=dict(range=[0, tw]),
                yaxis=dict(range=[0, td]),
                zaxis=dict(range=[0, th])
            ))
            st.plotly_chart(fig)

        # Detail Report
        st.subheader("Fragility Report") 
        for r in fragility_report:
            if r["safe"]:
                st.success(f"✅ {r['name']} SAFE")
            else:
                st.error(f"⚠️ {r['name']} OVERLOADED")
