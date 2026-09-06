"""
services/cctv_manager.py
========================
Per-dock CCTV image replacement manager (Task 4.1).

The canonical CCTV input for every dock remains `Fleet.cctv_frame_path`
(state/fleet_state.py). This module does NOT create a competing CCTV store —
it only:

  1. offers the "Change CCTV Image" UI inside an individual dock screening
     view — Upload -> Preview -> Save (no preset gallery, no reset),
  2. validates uploads (type / corruption / size) before anything is written,
  3. stages an uploaded file in memory for preview (uploading alone never
     replaces the dock's active CCTV source — only an explicit Save does),
  4. on Save, persists the file to assets/cctv_uploads/ (content-addressed,
     gitignored, separate from the pinned mock assets) and points the dock's
     Fleet at it,
  5. persists the operator's choice in a small session map and re-applies it to
     the dock's Fleet on every rerun (mock docks are re-seeded from JSON and
     Dock 1's monitor fleet re-pins its placeholder asset — both would
     otherwise overwrite the operator's choice),
  6. resolves the dock -> current CCTV image path for downstream Gemini code,
     so the scanner never needs to know whether the image came from a
     placeholder, the worker pipeline, or an operator upload.

HARD RULE: changing a CCTV image NEVER triggers Gemini. It only updates the
dock's current CCTV input and stamps DockState.cctv_updated_at so the previous
scan result is shown as STALE until the next "SCAN ALL DOCKS".

HARD RULE: the change UI is hosted ONLY in the individual dock screening view
(components/tri_view_panel.py). The Executive Dashboard must never expose a
Change CCTV control, preset gallery, or repository-image picker.
"""

import hashlib
import io
import os
from typing import Dict, List, Optional, Tuple

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRAMES_DIR = os.path.join(_BASE_DIR, "assets", "cctv_frames")
_IMG_DIR = os.path.join(_BASE_DIR, "img")
_UPLOAD_DIR = os.path.join(_BASE_DIR, "assets", "cctv_uploads")

_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')
# Maximum accepted upload size (bytes). Rejects oversized files before any
# write so they can never corrupt the current CCTV source.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

_SELECTION_KEY = "cctv_selections"


# --- helpers -----------------------------------------------------------------

def _ss():
    import streamlit as st
    return st.session_state


def _selections() -> Dict[int, str]:
    return _ss().setdefault(_SELECTION_KEY, {})


def _apply_to_fleet(dock_number: int, path: str):
    """Write the selection into the dock's canonical Fleet.cctv_frame_path."""
    from state.dock_state import get_dock_state
    dock = get_dock_state(dock_number)
    fleet = dock.fleet() if dock else None
    if fleet is not None:
        fleet.cctv_frame_path = path


def _sniff_image_ext(data: bytes) -> str:
    """
    Return the file extension (e.g. '.png') for the image format of ``data`` by
    sniffing its content with PIL, or '' if it cannot be identified. This keeps
    the stored name content-addressed and independent of the upload filename.
    """
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
        if fmt:
            return "." + fmt.lower()
    except Exception:
        return ""
    return ""


# --- public API --------------------------------------------------------------

def get_selection(dock_number: int) -> Optional[str]:
    """The operator-selected CCTV path for a dock (None when unchanged)."""
    return _selections().get(dock_number)


def set_dock_cctv(dock_number: int, path: str):
    """
    Replace the current CCTV input of a dock.

    Updates the canonical `Fleet.cctv_frame_path`, remembers the selection so
    it survives re-seeding, and stamps DockState.cctv_updated_at. NEVER
    triggers a Gemini analysis — no API call, no notification, no anomaly.

    Hardening: the active CCTV source is only ever pointed at a real file on
    disk. A staged/in-memory blob or a missing file can never become the
    dock's active CCTV input.
    """
    if not path:
        return
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return
    _selections()[dock_number] = path
    _apply_to_fleet(dock_number, path)

    from state.dock_state import mark_dock_cctv_changed
    mark_dock_cctv_changed(dock_number)


def validate_uploaded_image(filename: str, data: bytes) -> Tuple[bool, str]:
    """
    Validate an upload before anything is written or any state is mutated.

    Returns (ok, message). On failure, ``message`` is a human-readable reason
    suitable for display in the UI. An invalid upload never corrupts the
    current CCTV source.
    """
    if not data:
        return False, "Uploaded file is empty."

    name = filename or ""
    ext = os.path.splitext(name)[1].lower()
    if ext not in _IMAGE_EXTS:
        shown = ext if ext else "(none)"
        accepted = ", ".join(_IMAGE_EXTS)
        return False, (
            f"Unsupported file type '{shown}'. Accepted: {accepted}."
        )

    if len(data) > MAX_UPLOAD_BYTES:
        mb = len(data) // (1024 * 1024)
        limit = MAX_UPLOAD_BYTES // (1024 * 1024)
        return False, (
            f"File is too large ({mb} MB). Maximum is {limit} MB."
        )

    # Structural + decode check. verify() parses headers; a second open() +
    # load() forces a full decode so truncated/corrupt payloads are caught.
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            im.load()
    except Exception as exc:
        return False, f"Invalid or corrupt image file: {exc}"

    return True, ""


def persist_uploaded_cctv(
    dock_number: int, filename: str, data: bytes
) -> Optional[str]:
    """
    Persist an already-validated upload to assets/cctv_uploads/ under a
    content-addressed name (identical bytes are not re-written). The original
    filename is NOT used for storage — only its extension — so unsafe names and
    path-traversal inputs are harmless by construction. Returns the stored path
    or None on write failure.
    """
    os.makedirs(_UPLOAD_DIR, exist_ok=True)

    # Derive the extension from the ACTUAL image content (PIL format sniffing)
    # rather than the (untrusted, attacker-controlled) filename. This makes the
    # stored name genuinely content-addressed: identical bytes always yield the
    # identical stored path, whatever the upload was named. Fall back to the
    # filename extension, then .jpg, only when content sniffing is unavailable.
    ext = _sniff_image_ext(data) or os.path.splitext(filename or "")[1].lower()
    if ext not in _IMAGE_EXTS:
        ext = ".jpg"

    digest = hashlib.sha256(data).hexdigest()[:12]
    path = os.path.join(_UPLOAD_DIR, f"cctv_dock{dock_number}_{digest}{ext}")

    if os.path.exists(path):
        return path

    try:
        with open(path, "wb") as fh:
            fh.write(data)
    except Exception:
        return None
    return path

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
                cctv = ensure_dock_assets(dn)
                if cctv:
                    fleet.cctv_frame_path = cctv
            except Exception:
                pass


def handle_cctv_upload(
    dock_number: int, filename: str, data: bytes
) -> Optional[str]:
    """
    Save-step for an uploaded CCTV frame (called ONLY from the explicit
    "Save CCTV Image" action). Validates the upload, persists it to
    assets/cctv_uploads/ (content-addressed — identical bytes are not
    re-written), and selects it as the dock's active CCTV source.

    Validation happens first so an invalid/oversized/corrupt upload can never
    be written and can never corrupt the current CCTV source. Returns the stored
    path or None. Does NOT trigger any analysis.
    """
    if not data:
        return None

    ok, _message = validate_uploaded_image(filename, data)
    if not ok:
        return None

    path = persist_uploaded_cctv(dock_number, filename, data)
    if path is None:
        return None

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
        cctv = ensure_dock_assets(dock_number)
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


def restore_dock_cctv_selection(dock_number: int) -> Optional[str]:
    """Return the operator-selected path for a dock (or None) without applying."""
    return get_selection(dock_number)


# --- UI ----------------------------------------------------------------------

def render_cctv_change_control(dock_number: int):
    """
    Realistic per-dock "Change CCTV Image" workflow: Upload -> Preview -> Save.

    Uploading a file ONLY stages it for preview — it never replaces the dock's
    active CCTV source. The active source changes ONLY when the operator presses
    "Save CCTV Image". There is no preset gallery and no repository-image picker,
    so the operator cannot browse or switch between existing dock assets.

    Invalid uploads (wrong type, corrupt, empty, oversized) are rejected before
    anything is written, so they can never corrupt the current CCTV source.
    Changing the image NEVER triggers analysis.
    """
    import streamlit as st

    current = resolve_dock_cctv(dock_number)
    staged_key = f"cctv_staged_{dock_number}"
    last_validated_key = f"cctv_last_validated_{dock_number}"
    saved_marker_key = f"cctv_saved_{dock_number}"

    with st.expander("📷 Change CCTV Image", expanded=False):
        st.caption(
            "Upload a new CCTV frame for this dock, preview it, then press Save. "
            "The new image becomes this dock's CCTV input — no analysis is triggered."
        )

        # --- 1. Ingest the uploaded file (staging only; never mutates fleet state) ---
        uploaded = st.file_uploader(
            "Upload new CCTV frame",
            type=["jpg", "jpeg", "png", "webp", "bmp"],
            key=f"cctv_upload_{dock_number}",
            help="Accepted: jpg, jpeg, png, webp, bmp. Max 10 MB.",
        )

        marker = None
        data = b""
        if uploaded is not None:
            name = getattr(uploaded, "name", "upload.jpg")
            try:
                data = uploaded.getvalue()
            except Exception:
                data = b""
            size = len(data)
            digest = hashlib.sha256(data).hexdigest()[:16]
            marker = (name, size, digest)

        ss = _ss()
        last_validated = ss.get(last_validated_key)

        # Validate + stage a distinct uploaded file exactly once.
        if marker is not None and marker != last_validated:
            ok, message = validate_uploaded_image(
                uploaded.name if uploaded is not None else "upload.jpg", data
            )
            ss[last_validated_key] = marker
            if ok:
                ss[staged_key] = {
                    "data": data,
                    "name": getattr(uploaded, "name", "upload.jpg"),
                    "marker": marker,
                }
            else:
                ss.pop(staged_key, None)
                st.error(message)

        staged = ss.get(staged_key)
        saved_marker = ss.get(saved_marker_key)

        # --- 2. Preview + explicit Save (only when a valid, unsaved file is staged) ---
        if staged is not None and staged.get("marker") != saved_marker:
            st.markdown("**Preview**")
            st.image(staged["data"], width="stretch")
            st.caption(
                f"Preview of {staged['name']} — press **Save CCTV Image** to make it "
                f"the active CCTV source for Dock {dock_number}."
            )
            if st.button(
                "💾 Save CCTV Image",
                key=f"cctv_save_{dock_number}",
                type="primary",
                width="stretch",
            ):
                path = handle_cctv_upload(
                    dock_number, staged["name"], staged["data"]
                )
                if path:
                    ss[saved_marker_key] = staged["marker"]
                    ss.pop(staged_key, None)
                    st.toast(
                        f"✅ Dock {dock_number} CCTV image saved (no analysis triggered)",
                        icon="📷",
                    )
                    st.rerun()
                else:
                    st.error(
                        "Could not save the image — validation failed. "
                        "The current CCTV image is unchanged."
                    )

        # Confirmation once the staged file has been saved.
        if (
            saved_marker is not None
            and staged is None
            and marker is not None
            and marker == saved_marker
        ):
            st.success(
                f"✅ Active CCTV image updated for Dock {dock_number} "
                "(saved — no analysis triggered)."
            )

        # --- 3. Always show the dock's current active CCTV image ---
        st.markdown("---")
        st.markdown("**Active CCTV image**")
        if current and os.path.isfile(current):
            st.image(current, width="stretch")
            st.caption(f"Active CCTV input: {os.path.basename(current)}")
        else:
            st.caption("No CCTV image available for this dock.")