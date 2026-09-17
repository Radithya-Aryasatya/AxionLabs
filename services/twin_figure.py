# services/twin_figure.py - DIRECT COPY of Dock 1 painter
# Axis mapping identical to Dock 1. Truck lies flat, 6 m depth horizontal.
# No streamlit inside. Pipeline calls build_twin_figure.
import plotly.graph_objects as go
from dataclasses import dataclass
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

_TWIN_COLOR_MAP = {}

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



    global _TWIN_COLOR_MAP



    # Remove instance number

    base_name = name.split("#")[0].strip()



    if base_name not in _TWIN_COLOR_MAP:

        idx = len(_TWIN_COLOR_MAP) % len(palette)

        _TWIN_COLOR_MAP[base_name] = palette[idx]



    return _TWIN_COLOR_MAP[base_name]





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





# Adapter: pipeline-friendly wrapper around the DIRECT COPY above.
# Same axis mapping and style as Dock 1. Called by mock seeding + tri-view fallback.
def build_twin_figure(packed_items_cm, truck_dims_m, part_number=''):
    if not packed_items_cm:
        return None
    items = []
    for p in packed_items_cm:
        pos, dim = p['position'], p['dimensions']
        items.append(PackedItem(name=str(p.get('name', '')), x=float(pos[0])/100.0, y=float(pos[1])/100.0, z=float(pos[2])/100.0, w=float(dim[0])/100.0, h=float(dim[1])/100.0, d=float(dim[2])/100.0, weight=float(p.get('weight', 0)), max_load=0))
    return render_3d_packing_plot(items, (float(truck_dims_m[0]), float(truck_dims_m[1]), float(truck_dims_m[2])))
