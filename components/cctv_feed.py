"""
components/cctv_feed.py
=======================
CCTV Live Stream & Depth View component.

  - Renders current CCTV frame/video inside the truck interior
  - Includes a Toggle Switch: [ Standard RGB Feed ] vs [ Depth Map (Depth Anything V2) ]
"""

import streamlit as st
import os
from datetime import datetime
from services.cctv_simulator import get_cctv_simulator

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def render_cctv_feed(
    dock_number: int,
    cctv_frame_path: str = "",
    depth_map_path: str = "",
    width: int = 512,
    height: int = 384,
):
    """
    Render the CCTV live stream panel with RGB/Depth toggle.
    """
    sim = get_cctv_simulator()

    if not cctv_frame_path:
        cctv_frame_path = sim.get_frame(dock_number)
    if not depth_map_path:
        depth_map_path = sim.get_depth_map(dock_number)

    # Toggle switch for RGB vs Depth
    view_mode = st.radio(
        "Feed Mode",
        options=["Standard RGB Feed", "Depth Map (Depth Anything V2)"],
        horizontal=True,
        index=0,
        key=f"cctv_view_mode_{dock_number}",
    )

    st.markdown("---")

    # Simulate "live" by cycling frames
    image_sources = []
    img_dir = os.path.join(_BASE_DIR, "img")
    if os.path.exists(img_dir):
        for f in sorted(os.listdir(img_dir)):
            if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                image_sources.append(os.path.join(img_dir, f))

    if image_sources:
        frame_idx = dock_number % len(image_sources)
        time_idx = int(datetime.now().timestamp() / 3) % len(image_sources)
        final_idx = (frame_idx + time_idx) % len(image_sources)
        current_frame = image_sources[final_idx]
    else:
        current_frame = cctv_frame_path

    if view_mode == "Standard RGB Feed":
        _render_rgb_feed(current_frame, width, height)
    else:
        _render_depth_feed(depth_map_path or current_frame, width, height)

    st.caption(f"📹 Live Feed | Dock {dock_number} | Last updated: {datetime.now().strftime('%H:%M:%S')}")


def _render_rgb_feed(frame_path: str, width: int, height: int):
    """Render the standard RGB CCTV feed."""
    if frame_path and os.path.exists(frame_path):
        st.image(
            frame_path,
            caption="🚛 CCTV Standard RGB Feed (Live)",
            width='stretch',
        )
    else:
        st.markdown("""
            <div style="
                width: 100%;
                height: 250px;
                background: linear-gradient(135deg, #1e293b 0%, #334159 100%);
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: #64748b;
                border: 2px dashed #475569;
            ">
                <div style="text-align: center;">
                    <div style="font-size: 20px; margin-bottom: 8px;">📹</div>
                    <div>CCTV Feed Placeholder</div>
                    <div style="font-size: 12px; margin-top: 4px;">
                        (No camera feed available)
                    </div>
                </div>
            </div>
        """, unsafe_allow_html=True)


def _render_depth_feed(depth_path: str, width: int, height: int):
    """Render the depth map feed (Depth Anything V2 output)."""
    if depth_path and os.path.exists(depth_path):
        st.image(
            depth_path,
            caption="🎯 Depth Map (Depth Anything V2)",
            width='stretch',
        )
        st.markdown("""
            <div style="
                background: #1e293b;
                border-radius: 6px;
                padding: 8px 12px;
                margin-top: 8px;
            ">
                <div style="color: #94A3B8; font-size: 12px;">
                    <strong>Depth Legend:</strong>
                    <span style="color: #10B981;">● Near</span> ·
                    <span style="color: #F59E0B;">● Mid</span> ·
                    <span style="color: #EF4444;">● Far</span>
                </div>
            </div>
        """, unsafe_allow_html=True)
    else:
        # Generate a visual placeholder depth map
        st.markdown("""
            <div style="
                width: 100%;
                height: 250px;
                background: linear-gradient(135deg, #052e16 0%, #78350b 50%, #7f1d1d 100%);
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: #64748b;
                border: 2px dashed #475569;
            ">
                <div style="text-align: center;">
                    <div style="font-size: 20px; margin-bottom: 8px;">🎯</div>
                    <div>Depth Map (Depth Anything V2)</div>
                    <div style="font-size: 12px; margin-top: 4px;">
                        <span style="color: #10B981;">● Near</span> ·
                        <span style="color: #F59E0B;">● Mid</span> ·
                        <span style="color: #EF4444;">● Far</span>
                    </div>
                </div>
            </div>
        """, unsafe_allow_html=True)
