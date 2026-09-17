"""services/twin_figure.py
Shared Digital-Twin 3D figure builder (Gold Standard).

Dock 1 draws its pretty solid-color boxes with black edges in app.py
(render_3d_packing_plot). Docks 2/3/4 previously used a weaker translucent
per-face drawer in mock_fleet_factory, which is why they never looked the
same. This module is the ONE painter every dock uses now:

  build_twin_figure(packed_items_cm, truck_dims_m, part_number)
    packed_items_cm: list of dicts with position/dimensions in CM
                     (same convention as packing_layout['layout'])
    truck_dims_m:    (W, H, D) in meters, e.g. (2.4, 2.4, 6.0)
    part_number:     bin key, e.g. 'MOCK-D2'

Returns a plotly Figure with solid Mesh3d boxes + black edges, Width /
Height / Depth meter axes and the red rear-door strip - identical style
to the worker view. Pure function: no streamlit, no session state, so it
is safe to call from seeding, fallbacks and tests.
"""
import plotly.graph_objects as go

PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f",
]


def _color_for(base_name, color_map):
    if base_name not in color_map:
        color_map[base_name] = PALETTE[len(color_map) % len(PALETTE)]
    return color_map[base_name]


def _box_mesh(x, y, z, w, h, d, color):
    x0, x1 = x, x + w
    y0, y1 = y, y + h
    z0, z1 = z, z + d
    return go.Mesh3d(
        x=[x0, x1, x1, x0, x0, x1, x1, x0],
        y=[y0, y0, y1, y1, y0, y0, y1, y1],
        z=[z0, z0, z0, z0, z1, z1, z1, z1],
        i=[0, 0, 0, 1, 4, 4, 4, 5, 2, 2, 2, 3],
        j=[1, 2, 3, 2, 5, 6, 7, 6, 6, 7, 4, 4],
        k=[3, 3, 1, 3, 7, 7, 5, 7, 7, 5, 5, 0],
        color=color, opacity=1.0, flatshading=True,
        hoverinfo="skip", showlegend=False,
    )


def _box_edges(x, y, z, w, h, d):
    x0, x1 = x, x + w
    y0, y1 = y, y + h
    z0, z1 = z, z + d
    pts = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
           (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    segs = [(0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7)]
    xs, ys, zs = [], [], []
    for a, b2 in segs:
        xs += [pts[a][0], pts[b2][0], None]
        ys += [pts[a][1], pts[b2][1], None]
        zs += [pts[a][2], pts[b2][2], None]
    return go.Scatter3d(x=xs, y=ys, z=zs, mode="lines",
                        line=dict(color="black", width=4),
                        hoverinfo="skip", showlegend=False)



def build_twin_figure(packed_items_cm, truck_dims_m, part_number=""):
    """Build the Gold-Standard twin figure. Returns None when empty."""
    if not packed_items_cm:
        return None
    truck_w, truck_h, truck_d = (float(truck_dims_m[0]),
                                 float(truck_dims_m[1]),
                                 float(truck_dims_m[2]))
    fig = go.Figure()
    rear_depth = truck_d * 0.08
    fig.add_trace(go.Mesh3d(
        x=[0, truck_w, truck_w, 0, 0, truck_w, truck_w, 0],
        y=[0, 0, truck_h, truck_h, 0, 0, truck_h, truck_h],
        z=[truck_d - rear_depth] * 4 + [truck_d] * 4,
        i=[0, 0, 0, 1, 4, 4, 4, 5, 2, 2, 2, 3],
        j=[1, 2, 3, 2, 5, 6, 7, 6, 6, 7, 4, 4],
        k=[3, 3, 1, 3, 7, 7, 5, 7, 7, 5, 5, 0],
        color="red", opacity=0.3, flatshading=True,
        hoverinfo="skip", showlegend=False, name="Rear Loading Door",
    ))
    color_map = {}
    for item in packed_items_cm:
        pos, dim = item["position"], item["dimensions"]
        x, y, z = pos[0] / 100.0, pos[1] / 100.0, pos[2] / 100.0
        w, h, d = dim[0] / 100.0, dim[1] / 100.0, dim[2] / 100.0
        base = str(item.get("name", "")).split("#")[0].strip()
        color = _color_for(base, color_map)
        fig.add_trace(_box_mesh(x, y, z, w, h, d, color))
        fig.add_trace(_box_edges(x, y, z, w, h, d))
    fig.update_layout(
        title=f"3D Bin Packing Layout Matrix ({part_number})",
        scene=dict(
            xaxis=dict(title="Width", range=[0, truck_w]),
            yaxis=dict(title="Height", range=[0, truck_h]),
            zaxis=dict(title="Depth", range=[0, truck_d]),
            aspectmode="data",
            camera=dict(eye=dict(x=1.7, y=-1.7, z=1.2)),
        ),
        autosize=True, height=600, margin=dict(l=0, r=0, b=0, t=40),
    )
    return fig
