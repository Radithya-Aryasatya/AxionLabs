"""
components/cargo_manifest_panel.py
===================================
Cargo Manifest & Status panel for the Fleet Detail Inspection View.

Displays:
  - Cargo manifest status (Loaded vs Remaining items)
  - Per-item: quantity, packed/remaining counts, fragile flag, weight
"""

import streamlit as st
from state.fleet_state import Fleet
from utils.formatters import render_colored_progress


def render_cargo_manifest(fleet: Fleet):
    """
    Render the cargo manifest status panel.

    Parameters
    ----------
    fleet : Fleet
        The fleet whose manifest will be displayed.
    """
    manifest_summary = fleet.packing_layout.get('manifest_summary', [])
    total_expected = fleet.packing_layout.get('total_items_expected', 0)
    packed_count = fleet.packing_layout.get('packed_count', 0)
    unfitted_count = fleet.packing_layout.get('unfitted_count', 0)
    remaining_count = total_expected - packed_count

    # --- Header Metrics ---
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Expected", total_expected)
    with col2:
        st.metric("Packed", packed_count)
    with col3:
        st.metric("Remaining", remaining_count,
                  delta=-remaining_count if remaining_count > 0 else 0)
    with col4:
        st.metric("Unfitted", unfitted_count)

    st.markdown("---")

    # --- Loaded Items (packed successfully) ---
    st.subheader("📦 Loaded Items")

    loaded_items = [
        item for item in manifest_summary if item.get('packed', 0) > 0
    ]

    if loaded_items:
        for item in loaded_items:
            _render_manifest_item_row(item, status="loaded")
    else:
        st.info("No items have been loaded yet.")

    st.markdown("---")

    # --- Remaining Items (not yet packed) ---
    st.subheader("⏳ Remaining Items")

    remaining_items = [
        item for item in manifest_summary
        if (item.get('remaining', 0) > 0 or item.get('packed', 0) == 0)
    ]

    if remaining_items:
        for item in remaining_items:
            _render_manifest_item_row(item, status="remaining")
    else:
        st.success("✅ All items packed successfully!")

    # --- Unfitted Items ---
    unfitted_items = fleet.packing_layout.get('layout', {}).get('unfitted_items', [])
    if unfitted_items:
        st.markdown("---")
        st.subheader("⚠️ Unpacked Items (Rejected by Constraints)")
        for item in unfitted_items:
            st.error(f"**{item['name']}** could not be packed securely.")

    # --- Total Weight & Volume Summary ---
    st.markdown("---")
    _render_summary(fleet)


def _render_manifest_item_row(item: dict, status: str = "loaded"):
    """Render a single manifest item row with progress bar."""
    name = item.get('name', 'Unknown')
    quantity = item.get('quantity', 1)
    packed = item.get('packed', 0)
    remaining = item.get('remaining', quantity - packed)
    fragile = item.get('fragile', False)
    weight = item.get('weight', 0) if 'weight' in item else 0
    max_load = item.get('max_load', 0)

    # Visual indicator
    status_icon = "✅" if status == "loaded" else "⏳"
    fragile_badge = " 🛑FRAGILE" if fragile else ""

    st.markdown(f"""
        **{status_icon} {name}**{fragile_badge}
    """)

    col1, col2, col3 = st.columns([5, 3, 2])
    with col1:
        progress = packed / quantity if quantity > 0 else 0
        render_colored_progress(progress * 100)
    with col2:
        st.caption(f"Packed: {packed}/{quantity}")
    with col3:
        if weight or max_load:
            st.caption(f"Load: {max_load} kg")


def _render_summary(fleet: Fleet):
    """Render total weight and volume summary."""
    layout = fleet.packing_layout
    packed_items = layout.get('layout', {}).get('packed_items', [])

    total_weight = sum(p.get('weight', 0) for p in packed_items)
    truck_w, truck_h, truck_d = fleet.truck_dimensions
    truck_volume_m3 = truck_w * truck_h * truck_d

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Cargo Weight", f"{total_weight:.0f} kg")
    with col2:
        st.metric("Truck Volume", f"{truck_volume_m3:.2f} m³")
