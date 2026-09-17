"""tools/build_dock_twins.py
Builds REAL digital-twin layouts for Dock 2/3/4 from the swap-folder Excel
files. THIN SHIM: all packing now lives in services/dock234_engine.py -- the
faithful PHOTOCOPY of Dock 1's py3dbp brain (stability >=75% support,
updown=False, gravity, soft-LIFO sequence). The old shelf_pack placeholder
is deleted; there is exactly ONE brain for docks 2/3/4.

Sequence ON/OFF per dock: dock_manifests/dockN_sequence.txt (ON/OFF, VSCODE
only; default ON).

Run:  python AxionLabs/tools/build_dock_twins.py
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from services import dock234_engine as engine  # noqa: E402

MOCK_DIR = os.path.join(BASE_DIR, "assets", "mock_docks")
_MANIFEST_DIR = os.path.join(BASE_DIR, "dock_manifests")

TRUCK_W_M, TRUCK_H_M, TRUCK_D_M = 2.4, 2.4, 6.0
TRUCK_W, TRUCK_H, TRUCK_D = 240.0, 240.0, 600.0


def read_demo_sheet(xlsx_path):
    """Kept for mock_fleet_factory compatibility; delegates to the engine."""
    return engine.read_manifest_from_excel(xlsx_path)


def build_layout(dock_number, rows):
    """Delegate to the photocopied engine (accepts either row shape)."""
    return engine.build_layout(dock_number, rows)


def main():
    docks = [d for d in (2, 3, 4)
             if os.path.isfile(os.path.join(_MANIFEST_DIR,
                                            f"dock{d}_manifest.xlsx"))]
    if not docks:
        print("[build_dock_twins] No dock manifests in dock_manifests/ yet.")
        return
    for d in docks:
        engine.build_single_dock(d)


if __name__ == "__main__":
    main()
