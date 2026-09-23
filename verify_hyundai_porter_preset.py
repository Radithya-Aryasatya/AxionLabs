"""
verify_hyundai_porter_preset.py
===============================
Proves the new fleet-vehicle preset is wired end-to-end in the real app:

  Pass A (picker contents)
      "1. Define Vehicle Space -> Select Truck" offers "Hyundai Porter II" and
      labels it with the manual-input dimensions from the spec sheet
      (3.0 x 1.2 x 1.1 m).

  Pass B (auto-fill)
      Selecting "Hyundai Porter II" copies 1.20 / 1.10 / 3.00 into the manual
      Truck Width / Height / Depth inputs below it.

  Pass C (identity down the pipeline)
      Running a real pack with that truck selected registers the live fleet as
      "Hyundai Porter II" with dimensions (1.2, 1.1, 3.0) — the name the
      executive dashboard card and the invoice both read.

Run:  python verify_hyundai_porter_preset.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from streamlit.testing.v1 import AppTest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")

TRUCK_NAME = "Hyundai Porter II"
TRUCK_DIMS = (1.2, 1.1, 3.0)          # width, height, depth (m)
LABEL_TOKEN = "3.0 × 1.2 × 1.1"
PACK_LABEL = "Run AI Optimization"

MANIFEST = [{
    "name": "CrateA", "w": 0.5, "h": 0.5, "d": 0.5,
    "weight": 25.0, "quantity": 4, "max_load": 150.0, "sequence": 1,
}]

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    """Record a pass/fail line; failures are reported together at the end."""
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" -> {detail}" if detail else ""), flush=True)
    if not ok:
        FAILURES.append(label)


def _all_block_elements(at: AppTest, kind: str) -> list:
    """Sidebar widgets live on `at.sidebar`, body widgets on the AppTest root."""
    return list(getattr(at, kind)) + list(getattr(at.sidebar, kind))


def _radio(at: AppTest, key: str):
    for element in _all_block_elements(at, "radio"):
        if element.key == key:
            return element
    return None


def _number_input(at: AppTest, key: str):
    for element in _all_block_elements(at, "number_input"):
        if element.key == key:
            return element
    return None


def main() -> int:
    at = AppTest.from_file(APP, default_timeout=150)
    at.run()
    assert not at.exception, f"initial render: {[str(e) for e in at.exception][:2]}"

    # --- Pass A: the new truck is offered in the picker ------------------
    picker = _radio(at, "selected_truck")
    check("vehicle picker renders", picker is not None)
    if picker is None:
        return 1

    # `picker.options` exposes the FORMATTED labels (format_func is applied),
    # so match on the label prefix rather than the raw option value.
    labels = [str(option) for option in picker.options]
    porter_label = next((l for l in labels if l.startswith(TRUCK_NAME)), None)
    check(f"picker offers {TRUCK_NAME!r}", porter_label is not None, str(labels))
    check("picker labels it with the 3.0 × 1.2 × 1.1 m dimensions",
          porter_label is not None and LABEL_TOKEN in porter_label,
          str(porter_label))
    check("preset list is unchanged apart from the new entry",
          len(labels) == 7, f"{len(labels)} options")

    # --- Pass B: selecting it auto-fills the manual dimension inputs -----
    picker.set_value(TRUCK_NAME)
    at.run()
    assert not at.exception, f"after selecting {TRUCK_NAME}: {[str(e) for e in at.exception][:2]}"

    seeded = tuple(float(at.session_state[k]) for k in ("truck_w", "truck_h", "truck_d"))
    check("selection seeds session_state dims", seeded == TRUCK_DIMS, f"got {seeded}")

    shown = []
    for key in ("truck_w", "truck_h", "truck_d"):
        widget = _number_input(at, key)
        shown.append(None if widget is None else float(widget.value))
    shown = tuple(shown)
    check("manual inputs display the seeded dims", shown == TRUCK_DIMS, f"got {shown}")

    # The picker lives inside an expander titled after the selected truck.
    # `at.expander` is not exposed by every Streamlit version, so treat a
    # missing element list as "not checkable" instead of a failure.
    expanders = list(getattr(at, "expander", []))
    expander_labels = [str(getattr(e, "label", "")) for e in expanders]
    if expander_labels:
        check("expander title names the selected truck",
              any(TRUCK_NAME in label for label in expander_labels),
              str(expander_labels))
    else:
        print("[SKIP] expander elements are not exposed by this Streamlit version", flush=True)

    # --- Pass C: identity + dimensions reach the registered fleet --------
    at.session_state["manifest"] = MANIFEST
    buttons = [b for b in _all_block_elements(at, "button") if b.label == PACK_LABEL]
    check(f"{PACK_LABEL!r} button exists", bool(buttons))
    if not buttons:
        return 1

    buttons[0].click()
    at.run()
    assert not at.exception, f"after packing: {[str(e) for e in at.exception][:2]}"

    fleets = [f for f in at.session_state["active_fleets"] if f.source == "live"]
    check("a live fleet was registered", bool(fleets), f"count={len(fleets)}")
    if fleets:
        fleet = fleets[0]
        check("registered fleet carries the truck name",
              fleet.truck_name == TRUCK_NAME, fleet.truck_name)
        dims = tuple(round(float(v), 3) for v in fleet.truck_dimensions)
        check("registered fleet carries the truck dims",
              dims == TRUCK_DIMS, str(dims))

    print()
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} FAILED -> {FAILURES}")
        return 1
    print("RESULT: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
