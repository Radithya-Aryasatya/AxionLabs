"""
e2e_live_check.py
=================
REAL end-to-end check of the app's Gemini pipeline (no Streamlit server):
builds a Dock-1 fleet the same way the UI does, then runs
dock_pipeline.analyze_with_fallback against the REAL Gemini API.

Prints the honest provenance: status, source chip, model, raw response,
error. Never simulates, never falls back silently.

Run:  python e2e_live_check.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from state.fleet_state import Fleet, FleetStatus
from services.dock_pipeline import analyze_with_fallback
from services.mock_fleet_factory import ensure_dock_assets


def main() -> int:
    print("=" * 64)
    print("E2E LIVE PIPELINE CHECK (dock_pipeline -> Gemini API)")
    print("=" * 64)
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")
    print(f"Gemini API configured: {'YES' if api_key else 'NO'}")
    print(f"Gemini model: {os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}")

    cctv, depth = ensure_dock_assets(1)
    print(f"CCTV asset: {cctv} (exists={os.path.exists(cctv)})")
    print(f"Depth asset: {depth} (exists={os.path.exists(depth)})")

    fleet = Fleet(
        id="E2E-LIVE-01",
        dock_number=1,
        truck_dimensions=(2.0, 2.0, 4.0),
        manifest=[{"name": "CrateA", "quantity": 4, "fragile": False,
                   "max_load": 100}],
        packing_layout={
            "layout": {
                "part_number": "Truck",
                "WHD": (200.0, 200.0, 400.0),
                "packed_items": [
                    {"name": "CrateA #1", "part_number": "ITEM-0",
                     "position": [0, 0, 0], "dimensions": [50, 50, 50],
                     "weight": 90},
                    {"name": "CrateB #1", "part_number": "ITEM-1",
                     "position": [0, 50, 0], "dimensions": [50, 50, 50],
                     "weight": 30},
                ],
                "unfitted_items": [],
            },
            "manifest_summary": [
                {"name": "CrateA", "quantity": 4, "packed": 1, "remaining": 3,
                 "fragile": False, "max_load": 100},
            ],
            "total_items_expected": 4,
            "packed_count": 2,
            "unfitted_count": 0,
            "fill_percentage": 6.3,
        },
        status=FleetStatus.LOADING,
        fill_percentage=6.3,
        cctv_frame_path=cctv,
        depth_map_path=depth,
    )

    print("-" * 64)
    result, source = analyze_with_fallback(fleet)
    print("-" * 64)
    print(f"Provenance source chip : {source.value}")
    print(f"Result status          : {result.status}")
    print(f"Model                  : {result.model}")
    print(f"Anomaly type           : {result.anomaly_type}")
    print(f"Severity               : {result.severity}")
    print(f"Confidence             : {result.confidence}")
    print(f"Discrepancy score      : {result.spatial_discrepancy_score}")
    print(f"Error                  : {result.error or '(none)'}")
    print(f"Raw response length    : {len(result.raw_response or '')}")
    print("-" * 64)
    print("RAW GEMINI RESPONSE (exact):")
    print(result.raw_response or "(empty — no real Gemini content)")
    print("-" * 64)
    print(f"Structured paragraph   : {result.analysis_paragraph[:400]}")
    print(f"Recommended actions    : {result.recommended_actions}")
    print(f"Extra keys             : {list(result.extra.keys())}")

    ok = result.status == "SUCCESS" and bool(result.raw_response)
    print()
    print("VERDICT:", "REAL Gemini response received." if ok
          else "Gemini request did NOT produce a real response (see above).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
