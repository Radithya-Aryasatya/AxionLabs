"""
components/cctv_feed.py
=======================
CCTV Live Stream component.

  - Renders the current CCTV frame/video feed inside the truck interior
"""

import streamlit as st
import os
from services.cctv_simulator import get_cctv_simulator

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def render_cctv_feed(
    dock_number: int,
    cctv_frame_path: str = "",
    width: int = 512,
    height: int = 384,
):
    """
    Render the CCTV live stream panel (standard RGB feed).
    """
    sim = get_cctv_simulator()

    if not cctv_frame_path:
        cctv_frame_path = sim.get_frame(dock_number)

    st.markdown("---")

    # Deterministic frame selection (no time-based cycling)
    image_sources = []
    img_dir = os.path.join(_BASE_DIR, "img")
    if os.path.exists(img_dir):
        for f in sorted(os.listdir(img_dir)):
            if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                image_sources.append(os.path.join(img_dir, f))

    if image_sources:
        current_frame = image_sources[dock_number % len(image_sources)]
    else:
        current_frame = cctv_frame_path

    _render_rgb_feed(current_frame, width, height)

    st.caption(f"📹 CCTV Feed | Dock {dock_number} | Deterministic frame")


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
