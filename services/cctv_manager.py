"""
services/cctv_manager.py
========================
Per-dock CCTV image replacement manager (Task 4).

The canonical CCTV input for every dock remains `Fleet.cctv_frame_path`
(state/fleet_state.py). This module does NOT create a competing CCTV store —
it only:

  1. offers the "Change CCTV Image" UI (preset gallery + file upload),
  2. persists the operator's choice for that dock in a small session map,
  3. re-applies the choice to the dock's Fleet on every rerun (mock docks are
     re-seeded from JSON and Dock 1's monitor fleet re-pins its placeholder
     asset — both would otherwise overwrite the operator's choice),
  4. resolves the dock -> current CCTV image path for downstream Gemini code,
     so the scanner never needs to know whether the image came from a
     placeholder, the worker pipeline, or a presentation replacement.

HARD RULE: changing a CCTV image NEVER triggers Gemini. It only updates the
dock's current CCTV input and stamps DockState.cctv_updated_at so the previous
scan result is shown as STALE until the next "SCAN ALL DOCKS".
"""

import hashlib
import os
from typing import Dict, List, Optional, Tuple

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRAMES_DIR = os.path.join(_BASE_DIR, "assets", "cctv_frames")
_IMG_DIR = os.path.join(_BASE_DIR, "img")
_UPLOAD_DIR = os.path.join(_BASE_DIR, "assets", "cctv_uploads")

_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')

_SELECTION_KEY = "cctv_selections"


# --- helpers -----------------------------------------------------------------

def _ss():
    import streamlit as st
    return st.session_state


def _selections() -> Dict[int, str]:
    return _ss().setdefault(_SELECTION_KEY, {})


def _pretty_label(path: str) -> str:
    base = os.path.basename(path)
    name = os.path.splitext(base)[0].replace('_', ' ').replace('-', ' ').strip()
    return name[:40] if name else base


def _apply_to_fleet(dock_number: int, path: str):
    """Write the selection into the dock's canonical Fleet.cctv_frame_path."""
    from state.dock_state import get_dock_state
    dock = get_dock_state(dock_number)
    fleet = dock.fleet() if dock else None
    if fleet is not None:
        fleet.cctv_frame_path = path


# --- public API --------------------------------------------------------------

def available_cctv_images() -> List[Tuple[str, str]]:
    """
    Preset CCTV gallery for the change control: the four dock placeholder
    frames first, then the shared demo pool in img/. Returns [(label, path)].
    """
    out: List[Tuple[str, str]] = []
    if os.path.isdir(_FRAMES_DIR):
        for f in sorted(os.listdir(_FRAMES_DIR)):
            p = os.path.join(_FRAMES_DIR, f)
            if f.lower().endswith(_IMAGE_EXTS) and os.path.isfile(p):
                out.append((_pretty_label(p), p))
    if os.path.isdir(_IMG_DIR):
        for f in sorted(os.listdir(_IMG_DIR)):
            p = os.path.join(_IMG_DIR, f)
            if f.lower().endswith(_IMAGE_EXTS) and os.path.isfile(p):
                out.append((_pretty_label(p), p))
    return out


def get_selection(dock_number: int) -> Optional[str]:
    """The operator-selected CCTV path for a dock (None when unchanged)."""
    return _selections().get(dock_number)


def set_dock_cctv(dock_number: int, path: str):
    """
    Replace the current CCTV input of a dock.

    Updates the canonical `Fleet.cctv_frame_path`, remembers the selection so
    it survives re-seeding, and stamps DockState.cctv_updated_at. NEVER
    triggers a Gemini analysis — no API call, no notification, no anomaly.
    """
    if not path:
        return
    path = os.path.abspath(path)
    _selections()[dock_number] = path
    _apply_to_fleet(dock_number, path)

    from state.dock_state import mark_dock_cctv_changed
    mark_dock_cctv_changed(dock_number)

def clear_cctv_selections(docks=(2, 3, 4)):
    """Drop operator selections (demo reset) and restore dock placeholders."""
    sels = _selections()
    for dn in docks:
        sels.pop(dn, None)
        from state.dock_state import get_dock_state
        dock = get_dock_state(dn)
        fleet = dock.fleet() if dock else None
        if fleet is not None:
            try:
                from services.mock_fleet_factory import ensure_dock_assets
                cctv, _depth = ensure_dock_assets(dn)
                if cctv:
                    fleet.cctv_frame_path = cctv
            except Exception:
                pass


def handle_cctv_upload(dock_number: int, uploaded_file) -> Optional[str]:
    """
    Persist an uploaded CCTV frame to assets/cctv_uploads/ (content-addressed
    name so identical files are not re-written) and select it. Returns the
    stored path or None. Does NOT trigger any analysis.
    """
    if uploaded_file is None:
        return None
    try:
        data = uploaded_file.getvalue()
    except Exception:
        try:
            data = uploaded_file.read()
        except Exception:
            return None
    if not data:
        return None

    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(uploaded_file.name)[1].lower() or ".jpg"
    if ext not in _IMAGE_EXTS:
        ext = ".jpg"
    digest = hashlib.sha256(data).hexdigest()[:12]
    path = os.path.join(_UPLOAD_DIR, f"cctv_dock{dock_number}_{digest}{ext}")
    if not os.path.exists(path):
        with open(path, "wb") as fh:
            fh.write(data)

    set_dock_cctv(dock_number, path)
    return path


def resolve_dock_cctv(dock_number: int) -> str:
    """
    Dock -> current CCTV image path. This is the single resolver every
    downstream consumer (UI thumbnail, Gemini scan) uses, so the Gemini code
    cannot tell placeholder, worker-paired and operator-uploaded inputs apart.
    """
    selection = get_selection(dock_number)
    if selection and os.path.isfile(selection):
        return selection

    from state.dock_state import get_dock_state
    dock = get_dock_state(dock_number)
    fleet = dock.fleet() if dock else None
    if fleet and fleet.cctv_frame_path and os.path.isfile(fleet.cctv_frame_path):
        return fleet.cctv_frame_path

    # Last resort: the deterministic placeholder asset for this dock.
    try:
        from services.mock_fleet_factory import ensure_dock_assets
        cctv, _depth = ensure_dock_assets(dock_number)
        if cctv and os.path.isfile(cctv):
            return cctv
    except Exception:
        pass
    return (fleet.cctv_frame_path if fleet else "") or (selection or "")


def apply_cctv_selections():
    """
    Re-apply every stored operator selection to its dock's Fleet. Called after
    seed_mock_docks() / ensure_dock1_monitor_fleet() so re-seeding never
    wipes the operator's chosen CCTV input.
    """
    sels = dict(_selections())
    for dock_number, path in sels.items():
        if path and os.path.isfile(path):
            _apply_to_fleet(dock_number, path)


def restore_dock_cctv_selection(dock_number: int) -> Optional[str]:
    """Return the operator-selected path for a dock (or None) without applying."""
    return get_selection(dock_number)


def placeholder_cctv_path(dock_number: int) -> str:
    """Deterministic placeholder asset path for a dock (ensures it exists)."""
    try:
        from services.mock_fleet_factory import ensure_dock_assets
        cctv, _depth = ensure_dock_assets(dock_number)
        return cctv
    except Exception:
        return ""


# --- UI ----------------------------------------------------------------------

def render_cctv_change_control(dock_number: int):
    """
    The per-dock "Change CCTV Image" control (preset gallery + upload).

    Streamlit reruns the whole script on every widget interaction, so a change
    is detected by comparing the widget value with the stored selection.
    Changing the image ONLY updates the dock's CCTV input — no analysis runs.
    """
    import streamlit as st

    current = resolve_dock_cctv(dock_number)
    gallery = available_cctv_images()

    # Option list: presets first; make sure the current image is always a
    # selectable option (e.g. an uploaded replacement).
    options = [p for _label, p in gallery]
    label_map = dict(gallery)
    if current and current not in options:
        options.insert(0, current)
        label_map[current] = "Current CCTV image"
    if not options:
        st.caption("No CCTV images available.")
        return

    default_idx = options.index(current) if current in options else 0

    with st.expander("📷 Change CCTV Image", expanded=False):
        st.caption(
            "Pick a preset frame or upload a replacement. This only updates "
            "the dock's CCTV input — press SCAN ALL DOCKS to analyze it."
        )
        choice = st.selectbox(
            "CCTV source",
            options=options,
            index=default_idx,
            format_func=lambda p: label_map.get(p, _pretty_label(p)),
            key=f"cctv_select_{dock_number}",
        )
        if choice and choice != _selections().get(dock_number):
            set_dock_cctv(dock_number, choice)

        uploaded = st.file_uploader(
            "Upload new CCTV frame",
            type=["jpg", "jpeg", "png", "webp", "bmp"],
            key=f"cctv_upload_{dock_number}",
        )
        if uploaded is not None:
            try:
                size = len(uploaded.getvalue())
            except Exception:
                size = 0
            marker = (uploaded.name, size)
            if st.session_state.get(f"cctv_upload_done_{dock_number}") != marker:
                saved = handle_cctv_upload(dock_number, uploaded)
                if saved:
                    st.session_state[f"cctv_upload_done_{dock_number}"] = marker
                    st.toast(
                        f"Dock {dock_number} CCTV image replaced (no analysis triggered)",
                        icon="📷",
                    )
                    st.rerun()

        if st.button("↩️ Reset to dock placeholder",
                     key=f"cctv_reset_{dock_number}", width="stretch"):
            ph = placeholder_cctv_path(dock_number)
            if ph:
                set_dock_cctv(dock_number, ph)
                st.rerun()

        if current and os.path.isfile(current):
            st.image(current, width='stretch')
            st.caption(f"Current CCTV input: {os.path.basename(current)}")