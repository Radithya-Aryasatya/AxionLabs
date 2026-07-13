#orientation_editor.py
import streamlit as st
import plotly.graph_objects as go
from dataclasses import dataclass
from itertools import permutations


# ============================================================
# AXION LABS
# Orientation Editor
# ============================================================


@dataclass
class OrientationItem:
    name: str
    width: float
    height: float
    depth: float
    weight: float
    quantity: int
    max_load: float
    sequence: int


# ------------------------------------------------------------
# All legal cuboid orientations
# ------------------------------------------------------------

def generate_orientations(w, h, d):
    """
    Returns every unique orientation of a cuboid.

    Example

    200x100x50

    becomes

    200x100x50
    200x50x100
    100x200x50
    100x50x200
    50x200x100
    50x100x200
    """

    orientations = []

    for p in permutations([w, h, d]):
        if p not in orientations:
            orientations.append(p)

    return orientations


# ------------------------------------------------------------
# Session State Initializer
# ------------------------------------------------------------

def initialize_orientation_state(item):

    if "orientation_index" not in st.session_state:
        st.session_state.orientation_index = 0

    if "orientation_options" not in st.session_state:
        st.session_state.orientation_options = generate_orientations(
            item.width,
            item.height,
            item.depth
        )


# ------------------------------------------------------------
# Current Orientation
# ------------------------------------------------------------

def current_orientation():

    return st.session_state.orientation_options[
        st.session_state.orientation_index
    ]


# ------------------------------------------------------------
# Rotate
# ------------------------------------------------------------

def next_orientation():

    st.session_state.orientation_index += 1

    if st.session_state.orientation_index >= len(
        st.session_state.orientation_options
    ):
        st.session_state.orientation_index = 0


def previous_orientation():

    st.session_state.orientation_index -= 1

    if st.session_state.orientation_index < 0:

        st.session_state.orientation_index = (
            len(st.session_state.orientation_options) - 1
        )


# ------------------------------------------------------------
# 3D Preview
# ------------------------------------------------------------

def build_preview(item):

    w, h, d = current_orientation()

    fig = go.Figure()

    vx = [
        0,
        w,
        w,
        0,
        0,
        w,
        w,
        0
    ]

    vy = [
        0,
        0,
        0,
        0,
        d,
        d,
        d,
        d
        
    ]

    vz = [
        0,
        0,
        h,
        h,
        0,
        0,
        h,
        h
    ]

    i = [7,0,0,0,4,4,6,6,4,0,3,2]
    j = [3,4,1,2,5,6,5,2,0,1,6,3]
    k = [0,7,2,3,6,7,1,1,5,5,7,6]

    fig.add_trace(

        go.Mesh3d(

            x=vx,
            y=vy,
            z=vz,

            i=i,
            j=j,
            k=k,

            opacity=0.85,

            flatshading=True,

            color="royalblue",

            hovertemplate=(
                f"<b>{item.name}</b><br>"
                f"Width: {w} cm<br>"
                f"Height: {h} cm<br>"
                f"Depth: {d} cm<br>"
                f"Weight: {item.weight} kg"
                "<extra></extra>"
            ),
            lighting=dict(
                ambient=0.65,
                diffuse=0.9,
                roughness=0.4
            ),
        )

    )
    m = max(item.width, item.height, item.depth)

    world = max(item.width, item.height, item.depth) * 1.2

    fig.update_layout(

        title= dict(
            text="Cargo Preview",
            x=0.5,
            xanchor="center",
        ),
        margin=dict(
            l=0,
            r=0,
            b=0,
            t=40
        ),
        
        

        scene=dict(
            dragmode="orbit",

            

            xaxis=dict(
                title="Width",
                range=[0, world]
            ),

            yaxis=dict(
                title="Depth",
                range=[0, world]
            ),

            zaxis=dict(
                title="Height",
                range=[0, world]
            ),

            

            aspectmode="data",
            #aspectratio=dict(
                #x=w / m,
                #y=h / m,
                #z=d / m
            #),
            camera=dict(
                eye=dict(x=1.7, y=-1.7, z=1.2)
            ),
        )

    )

    return fig

# ============================================================
# Orientation UI
# ============================================================

def orientation_editor(item):

    initialize_orientation_state(item)

    st.subheader("📦 Cargo Orientation Editor")

    st.info(
        "Adjust the cargo orientation before "
        "adding it to the manifest."
    )

    left, right = st.columns([1, 2])

    # ---------------------------------------
    # LEFT PANEL
    # ---------------------------------------

    with left:

        w, h, d = current_orientation()

        st.divider()

        st.subheader("Orientation")

        st.caption(
            f"Rotation "
            f"{st.session_state.orientation_index + 1}"
            f" of "
            f"{len(st.session_state.orientation_options)}"
        )

        if st.button(
            "⟲ Previous Orientation",
            key="orientation_prev",
            use_container_width=True
        ):
            previous_orientation()
            st.rerun()

        if st.button(
        "⟳ Next Orientation",
        key="orientation_next",
        use_container_width=True
        ):
            next_orientation()
            st.rerun()

        st.divider()

        st.subheader("Cargo Information")

        info = {
            "Name": item.name,
            "Weight": f"{item.weight} kg",
            "Quantity": item.quantity,
            "Maximum Supported Load": f"{item.max_load} kg",
            "Unload Sequence": item.sequence,
            "Orientation": (
                f"{st.session_state.orientation_index + 1}"
                f" / "
                f"{len(st.session_state.orientation_options)}"
            ),
            "Dimensions": f"{w} × {h} × {d} cm"
        }

        st.table(info)

    # ---------------------------------------
    # RIGHT PANEL
    # ---------------------------------------

    with right:

        fig = build_preview(item)

        st.subheader("3D Preview")

        st.caption(
        "Drag with your mouse to inspect the cargo from different angles."
        )

        st.plotly_chart(
            fig,
            use_container_width=True,
            key="orientation_preview"
        )

    st.divider()


    st.subheader("Finalize")

    confirm_col, cancel_col = st.columns(2)

    confirmed = False

    cancelled = False

    with confirm_col:

        if st.button(
            "✅ Confirm Orientation",
            key="orientation_confirm",
            type="primary",
            use_container_width=True
        ):
            confirmed = True

    with cancel_col:

        if st.button(
            "❌ Cancel",
            key="orientation_cancel",
            use_container_width=True
        ):
            cancelled = True

    if cancelled:
        reset_orientation_editor()
        return None

    if confirmed:

        w, h, d = current_orientation()

        result = {

            "name": item.name,

            "w": w,

            "h": h,

            "d": d,

            "weight": item.weight,

            "quantity": item.quantity,

            "max_load": item.max_load,

            "sequence": item.sequence,

            "orientation_index": st.session_state.orientation_index
        }

        reset_orientation_editor()

        return result

    st.info(
    "Choose the desired orientation, then click "
    "'Confirm Orientation' to add this cargo."
    )

    return "WAITING"

# ============================================================
# Controller
# ============================================================

def launch_orientation_editor(
    name,
    width,
    height,
    depth,
    weight,
    quantity,
    max_load,
    sequence
):
    """
    Launches the orientation editor.

    Returns

    None
        User cancelled.

    "WAITING"
        User is still rotating.

    dict
        User confirmed.
    """

    item = OrientationItem(

        name=name,

        width=width,

        height=height,

        depth=depth,

        weight=weight,

        quantity=quantity,

        max_load=max_load,

        sequence=sequence
    )

    return orientation_editor(item)

# ============================================================
# Reset
# ============================================================

def reset_orientation_editor():

    keys = [

        "orientation_index",

        "orientation_options"

    ]

    for key in keys:

        if key in st.session_state:

            del st.session_state[key]
