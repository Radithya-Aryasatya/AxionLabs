"""
verify_render_lifecycle.py
==========================
Drives the REAL Streamlit app (app.py + all components) through Streamlit's
official AppTest harness and proves the worker-dashboard render lifecycle:

    Pack -> "Render 3D Packing Layout Matrix" -> "Remove Render" -> Pack again

The bug being guarded against: previously the ONLY way for a worker to retire
an existing 3D render and pack a freshly imported manifest was to hard-refresh
the whole browser page (F5). This script proves that never happens again:

  Pass A (no render yet)
      * no layout report, no "Remove Render" button.

  Pass B (after "Run AI Optimization")
      * "Optimal Layout Assignment" report is rendered and the render button is
        offered, but "Remove Render" is NOT offered yet.

  Pass C (after "Render 3D Packing Layout Matrix")
      * the per-bin visibility flag flips ON, the report stays, and the button
        slot SWAPS: "Remove Render" replaces "Render 3D Packing Layout Matrix"
        in the same position. The two labels are mutually exclusive -- the
        Render button has no remaining function while a render is live, so it
        must not be drawn next to the Remove button.

  Pass D (after "Remove Render")
      * session state is retracted AT CLICK TIME (every `show_render_*` flag ->
        False, `last_packer` / `layouts` / `last_3d_figure` dropped,
        `fleet_3d_figures` emptied) and, once the queued full-app rerun lands,
        the page carries no layout report, no 3D viewer and no
        "Remove Render" -- with no browser refresh. The worker can pack again
        immediately.

  Pass E (re-pack after removal)
      * a second "Run AI Optimization" rebuilds the report and the render
        button, proving removal left no corrupt state behind.

  Pass F (import a NEW manifest while a render is active)
      * uploading dock_manifests/dock2_manifest.xlsx and clicking
        "Import Manifest" auto-retires the live render (replacing the old F5
        workaround), so no stale layout/report survives the import.

  Pass G
      * static guard that the import handler calls `clear_worker_render()`
        BEFORE flipping `importing_manifest`, so the editor can never
        re-surface stale output.

NOTE ON `_settle()` -- why Pass D/F run the script one extra time
----------------------------------------------------------------
`clear_worker_render()` is followed by `st.rerun()`, which HALTS the current
script run and queues a full-app rerun (verified in Streamlit's source:
`execution_control._new_fragment_id_queue` returns `[]` for `scope="app"`).
AppTest merges the deltas of a halted run into its element tree instead of
dropping elements that the following run no longer emits, so `at.button` and
`at.subheader` briefly still show the *pre-rerun* page. A real browser instead
clears those nodes by `script_run_id` as soon as the full rerun lands.
`_settle()` reproduces that repaint; the run-counter experiment in
`tmp_repro2.py` proved the rerun genuinely executes (run counter 3 -> 5) and
that the stale elements then vanish. State assertions run BEFORE any settle, so
the test still proves the removal happens at click time, not later.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from streamlit.testing.v1 import AppTest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")
MANIFEST_XLSX = os.path.join(HERE, "dock_manifests", "dock2_manifest.xlsx")

MANIFEST = [{
    "name": "CrateA", "w": 0.5, "h": 0.5, "d": 0.5,
    "weight": 25.0, "quantity": 4, "max_load": 150.0, "sequence": 1,
}]

REPORT_TOKEN = "Optimal Layout Assignment"
RENDER_LABEL = "Render 3D Packing Layout Matrix"
REMOVE_LABEL = "Remove Render"
PACK_LABEL = "Run AI Optimization"
RETIRED_KEYS = ("last_packer", "layouts", "last_3d_figure")


def _log(msg: str) -> None:
    """Progress lines must land in the log file even when redirected."""
    print(msg, flush=True)


def _visible_text(at: AppTest) -> str:
    """Everything a user can read from markdown / subheaders / text / captions."""
    chunks = []
    for element in list(at.markdown) + list(at.subheader) + list(at.text) + list(at.caption):
        value = getattr(element, "value", None)
        if isinstance(value, str):
            chunks.append(value)
    return "\n".join(chunks)


def _buttons(at: AppTest, label: str) -> list:
    return [b for b in at.button if b.label == label]


def _has(at: AppTest, key: str) -> bool:
    """Membership for AppTest state.

    `at.session_state` is a SafeSessionState proxy, NOT a Mapping: attribute
    access is forwarded to `self[key]` (so `.get` is looked up as a KEY, not as
    `dict.get`), and `__iter__`/`keys()` are absent. Membership therefore has to
    go through `in`, and reads through `[]`.
    """
    return key in at.session_state


def _click(at: AppTest, label: str, step: str) -> None:
    """Click the first button with `label`, rerun, and fail loudly on errors."""
    matches = _buttons(at, label)
    assert matches, f"[{step}] button {label!r} not found in the element tree"
    matches[0].click()
    at.run()
    assert not at.exception, f"[{step}] {[str(e) for e in at.exception][:2]}"


def _settle(at: AppTest, step: str) -> None:
    """Execute the full-app rerun queued by `st.rerun()` (see module docstring)."""
    at.run()
    assert not at.exception, f"[{step}] settle run threw: {[str(e) for e in at.exception][:2]}"


def _render_flags(at: AppTest) -> dict:
    return {
        k: v for k, v in at.session_state.filtered_state.items()
        if isinstance(k, str) and k.startswith("show_render_")
    }


def _assert_state_retracted(at: AppTest, step: str) -> None:
    """Every worker-side render marker in session state must be gone."""
    flags = _render_flags(at)
    assert all(v is False for v in flags.values()), f"[{step}] flags still hot: {flags}"
    for dead in RETIRED_KEYS:
        assert not _has(at, dead), f"[{step}] {dead} survived removal"
    assert not at.session_state["fleet_3d_figures"], \
        f"[{step}] cached figures survived: {list(at.session_state['fleet_3d_figures'])}"


def _assert_page_retracted(at: AppTest, step: str) -> None:
    """Nothing render-related may still be painted on the worker's page."""
    assert REPORT_TOKEN not in _visible_text(at), f"[{step}] layout report still rendered"
    assert not _buttons(at, REMOVE_LABEL), f"[{step}] {REMOVE_LABEL!r} still offered"
    assert not _buttons(at, RENDER_LABEL), f"[{step}] 3D viewer still offered"


# --- MAIN --------------------------------------------------------------------
def main() -> int:
    at = AppTest.from_file(APP, default_timeout=600)

    # ---------------------------------------------------------------- Pass A
    at.run()
    assert not at.exception, f"[A] first run threw: {[str(e) for e in at.exception][:2]}"
    _assert_page_retracted(at, "A")
    _log(f"PASS A  cold start: no render, no {REMOVE_LABEL!r} button")

    # ---------------------------------------------------------------- Pass B
    at.session_state["manifest"] = MANIFEST
    _click(at, PACK_LABEL, "B")
    assert REPORT_TOKEN in _visible_text(at), "[B] layout report missing after packing"
    assert _buttons(at, RENDER_LABEL), f"[B] {RENDER_LABEL!r} missing after packing"
    assert not _buttons(at, REMOVE_LABEL), f"[B] {REMOVE_LABEL!r} offered before rendering"
    flags = _render_flags(at)
    assert flags and all(v is False for v in flags.values()), f"[B] flags: {flags}"
    bins = [b.partno for b in at.session_state["last_packer"].bins]
    _log(f"PASS B  packed -> report rendered, bins={bins}, flags={flags}, "
         f"{REMOVE_LABEL!r} correctly hidden")

    # ---------------------------------------------------------------- Pass C
    _click(at, RENDER_LABEL, "C")
    flags = _render_flags(at)
    assert any(v is True for v in flags.values()), f"[C] no flag flipped on: {flags}"
    assert _buttons(at, REMOVE_LABEL), f"[C] {REMOVE_LABEL!r} missing after rendering"
    assert not _buttons(at, RENDER_LABEL), \
        f"[C] {RENDER_LABEL!r} still drawn while a render is live (must swap, not stack)"
    assert REPORT_TOKEN in _visible_text(at), "[C] report vanished while rendering"
    assert _has(at, "last_3d_figure") and at.session_state["last_3d_figure"] is not None, \
        "[C] no 3D figure cached"
    assert at.session_state["fleet_3d_figures"], "[C] no per-bin figure cached"
    _log(f"PASS C  rendered -> {flags} hot, {RENDER_LABEL!r} swapped out for "
         f"{REMOVE_LABEL!r} in the same slot, 3D figure cached")

    # ---------------------------------------------------------------- Pass D
    _click(at, REMOVE_LABEL, "D")
    _assert_state_retracted(at, "D")          # retraction happens at click time
    _settle(at, "D")                          # queued full-app rerun repaints page
    _assert_page_retracted(at, "D")
    assert _buttons(at, PACK_LABEL), "[D] pack button gone -- worker cannot re-pack"
    _log("PASS D  remove -> state retracted at click time + page repainted, "
         f"{RENDER_LABEL!r} no longer shown (no browser refresh)")

    # ---------------------------------------------------------------- Pass E
    _click(at, PACK_LABEL, "E")
    assert REPORT_TOKEN in _visible_text(at), "[E] report missing after re-pack"
    assert _buttons(at, RENDER_LABEL), f"[E] {RENDER_LABEL!r} gone after re-pack"
    _click(at, RENDER_LABEL, "E")
    assert any(v is True for v in _render_flags(at).values()), "[E] render flag stayed off"
    assert _has(at, "last_3d_figure") and at.session_state["last_3d_figure"] is not None, \
        "[E] figure not rebuilt"
    _log("PASS E  re-pack after removal -> report + render rebuilt cleanly")

    # ---------------------------------------------------------------- Pass F
    # A brand-new manifest upload must retire the live render by itself.
    assert os.path.exists(MANIFEST_XLSX), f"missing fixture {MANIFEST_XLSX}"
    with open(MANIFEST_XLSX, "rb") as handle:
        xlsx_bytes = handle.read()

    uploaders = [f for f in at.file_uploader if f.label == "Upload Excel Manifest"]
    assert uploaders, "[F] manifest file uploader not found"
    uploaders[0].upload(
        os.path.basename(MANIFEST_XLSX), xlsx_bytes,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    at.run()
    assert not at.exception, f"[F] upload run threw: {[str(e) for e in at.exception][:2]}"
    assert any(v is True for v in _render_flags(at).values()), \
        "[F] render flag lost before the import click (test setup broken)"

    _click(at, "Import Manifest", "F")
    _assert_state_retracted(at, "F")
    _settle(at, "F")
    _assert_page_retracted(at, "F")
    _log("PASS F  new manifest import auto-retired the live render "
         f"(no manual {REMOVE_LABEL!r}, no hard refresh)")

    # ---------------------------------------------------------------- Pass G
    # Static call-site guard: the import handler must clear the render BEFORE
    # flipping `importing_manifest`, otherwise the editor can re-surface stale
    # output from the superseded manifest.
    source = open(APP, encoding="utf-8").read()
    ordering = re.search(
        r"st\.session_state\.import_queue\s*=\s*imported_items"
        r".*?clear_worker_render\(\)"
        r".*?st\.session_state\.importing_manifest\s*=\s*True",
        source, re.S,
    )
    assert ordering, \
        "import handler must call clear_worker_render() before importing_manifest=True"
    _log("PASS G  import-handler ordering guard (clear -> importing_manifest) intact")

    _log("\nALL RENDER-LIFECYCLE CHECKS PASSED -- a render can be removed and a "
         "new manifest packed without ever refreshing the page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

