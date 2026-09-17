"""
verify_invoice.py
=================
Validation for the "🖨 Print Invoice" feature (services/invoice_generator.py).

1. EXAMPLE PARITY — rebuilds the approved "AxionLabs Invoice.docx" numbers
   (194/198 packages, 2,593 kg / 2,773 kg planned, 21.95 m³ / 34.56 m³,
   63.5% utilization, 36 fragile units) as a synthetic dock fleet and
   asserts every section of the generated .docx matches the example.
2. DOCK-1 LIVE SHAPE — worker-imported manifests now carry package_id /
   destination city; Handling Instructions are gone by design (the table
   shows a Fragile flag instead). Asserts the new columns, the
   max_load-encoded fragile flag, and live-computed KPIs.

Writes (for eyeball inspection):
  assets/invoices/verify_example_parity.docx
  assets/invoices/verify_dock1_live.docx
"""

import io
import math
import os
import sys
from datetime import datetime

from docx import Document
from state.fleet_state import Fleet, FleetStatus
from services.invoice_generator import build_invoice_docx, invoice_doc_id

FIXED_NOW = datetime(2026, 9, 17)
FAILURES = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILURES.append(f"{name} {('— ' + str(detail)) if detail else ''}")


def _doc_text(data):
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts), doc


def _packed(name, w, dims, count):
    return [
        {"name": f"{name} #{k + 1}", "weight": w, "dimensions": list(dims)}
        for k in range(count)
    ]


def _example_fleet():
    """Synthetic Dock-2-style fleet reproducing the approved example numbers."""
    rows = [
        dict(name="PKG-2001 Standard Shipping Cartons (Electronics)",
             package_id="PKG-2001", quantity=50, packed=50, remaining=0,
             fragile=False, max_load=100, weight=8.5, dimensions=[50, 40, 40],
             zone="Zone A-1", sequence=1, city="Boston",
             handling="Standard stackable", tracking="TRK-9101"),
        dict(name="PKG-2002 Large Home Appliance Crates",
             package_id="PKG-2002", quantity=7, packed=3, remaining=4,
             fragile=True, max_load=10, weight=45.0,
             dimensions=[80, 80, 110], zone="Zone C-2", sequence=2,
             city="Atlanta", handling="Fragile - Base load only",
             tracking="TRK-9102"),
        dict(name="PKG-2003 Medium Storage Boxes (Apparel)",
             package_id="PKG-2003", quantity=61, packed=61, remaining=0,
             fragile=False, max_load=100, weight=10.0,
             dimensions=[50, 40, 35], zone="Zone A-3", sequence=3,
             city="Phoenix", handling="Standard stackable",
             tracking="TRK-9103"),
        dict(name="PKG-2004 Flat-Pack Furniture Cartons",
             package_id="PKG-2004", quantity=13, packed=13, remaining=0,
             fragile=False, max_load=100, weight=28.0,
             dimensions=[180, 60, 20], zone="Zone B-1", sequence=4,
             city="Portland", handling="Side-wall vertical placement",
             tracking="TRK-9104"),
        dict(name="PKG-2005 Glassware & Ceramic Cargo",
             package_id="PKG-2005", quantity=19, packed=19, remaining=0,
             fragile=True, max_load=10, weight=14.0, dimensions=[50, 40, 40],
             zone="Zone C-1", sequence=5, city="Austin",
             handling="Fragile - Top load only", tracking="TRK-9105"),
        dict(name="PKG-2006 Industrial Tool Cases", package_id="PKG-2006",
             quantity=14, packed=14, remaining=0, fragile=False, max_load=100,
             weight=22.0, dimensions=[100, 50, 40], zone="Zone B-2",
             sequence=6, city="Nashville", handling="Heavy load - Lower deck",
             tracking="TRK-9106"),
        dict(name="PKG-2007 Bulk Office Paper Trays", package_id="PKG-2007",
             quantity=24, packed=24, remaining=0, fragile=False, max_load=100,
             weight=12.5, dimensions=[50, 45, 40], zone="Zone A-2",
             sequence=7, city="Vegas", handling="Standard stackable",
             tracking="TRK-9107"),
        dict(name="PKG-2008 Precision LED Panels", package_id="PKG-2008",
             quantity=10, packed=10, remaining=0, fragile=True, max_load=10,
             weight=18.5, dimensions=[76, 60, 50], zone="Zone C-3",
             sequence=8, city="Charlotte",
             handling="Fragile - Handle with care", tracking="TRK-9108"),
    ]
    # Packed volume: 4.0 + 2.112 + 4.27 + 2.808 + 1.52 + 2.8 + 2.16 + 2.28
    #             = 21.95 m³  →  63.5% of the 34.56 m³ truck (the example).
    packed_items = []
    for r in rows:
        packed_items += _packed(r["name"], r["weight"], r["dimensions"],
                                r["packed"])
    plan = {
        "layout": {"packed_items": packed_items, "unfitted_items": []},
        "manifest_summary": rows,
        "total_items_expected": sum(r["quantity"] for r in rows),   # 198
        "packed_count": sum(r["packed"] for r in rows),             # 194
        "fill_percentage": 63.5,
        "sequence_priority": "ON",
    }
    return Fleet(id="TEST-D2", dock_number=2, truck_dimensions=(2.4, 2.4, 6.0),
                 manifest=rows, packing_layout=plan,
                 status=FleetStatus.INSPECTED_CLEAR, fill_percentage=63.5,
                 truck_name="Truck-2", source="mock")


def _dock1_fleet():
    """Dock-1 live shape: no package_id / city / handling / fragile keys."""
    manifest = [
        {"name": "Standard Shipping Cartons", "width": 0.5, "height": 0.4,
         "depth": 0.4, "weight": 8.5, "quantity": 50, "max_load": math.inf,
         "sequence": 1, "package_id": "PKG-1001", "city": "Rotterdam"},
        {"name": "Glassware & Ceramics", "width": 0.5, "height": 0.4,
         "depth": 0.4, "weight": 14.0, "quantity": 19, "max_load": 14.0,
         "sequence": 2, "package_id": "PKG-1002", "city": "Oslo"},
    ]
    summary = [
        {"name": "Standard Shipping Cartons", "package_id": "PKG-1001",
         "quantity": 50, "total_expected": 50, "packed": 50, "remaining": 0,
         "fragile": False, "max_load": math.inf, "city": "Rotterdam"},
        {"name": "Glassware & Ceramics", "package_id": "PKG-1002",
         "quantity": 19, "total_expected": 19, "packed": 19, "remaining": 0,
         "fragile": False, "max_load": 14.0, "city": "Oslo"},
    ]
    packed_items = (_packed("Standard Shipping Cartons", 8.5, [50, 40, 40], 50)
                    + _packed("Glassware & Ceramics", 14.0, [50, 40, 40], 19))
    plan = {
        "layout": {"packed_items": packed_items, "unfitted_items": []},
        "manifest_summary": summary,
        "total_items_expected": 69,
        "packed_count": 69,
        "fill_percentage": 16.0,
    }
    return Fleet(id="TK-01", dock_number=1, truck_dimensions=(2.4, 2.4, 6.0),
                 manifest=manifest, packing_layout=plan,
                 status=FleetStatus.INSPECTED_CLEAR, fill_percentage=16.0,
                 truck_name="Truck-1", source="live")


def _manifest_table(doc):
    for tbl in doc.tables:
        if tbl.rows and tbl.rows[0].cells[0].text.strip() == "Sequence":
            return tbl
    return None


def check_example_parity(out_dir):
    print("\n1) EXAMPLE PARITY (Dock 2 — the approved example numbers)")
    fleet = _example_fleet()
    data = build_invoice_docx(fleet, doc_id=invoice_doc_id(2, 1, now=FIXED_NOW))
    text, doc = _doc_text(data)

    check("company + title block", "PT. Kawan Lama Sejahtera" in text
          and "LOAD & PACKING INVOICE" in text)
    check("document ID AX-D2-20260917-01", "AX-D2-20260917-01" in text)
    check("meta strip", all(s in text for s in
                            ("Dock 2", "Truck-2", "FINISHED",
                             "DOCUMENT ID", "FLEET STATUS")))
    check("packages 194 / 198",
          "194 packages packed / 198 from manifest" in text)
    check("loaded weight 2,593 kg (2,773 kg planned)",
          "2,593 kg" in text and "2,773 kg planned total" in text)
    check("volume 21.95 m³ / 34.56 m³ at 63.5%",
          "21.95 m³ packed / 34.56 m³ truck" in text and "63.5%" in text)
    check("fragile cargo 36",
          "FRAGILE CARGO" in text and "Amount of objects requiring care" in text
          and "36" in text)
    check("load state + sequence priority",
          "Sequence priority: ON" in text and "CURRENT LOAD STATE" in text)
    check("truck profile", "2.4 × 2.4 × 6.0 m" in text)
    check("utilization caption",
          "63.5% occupied  •  36.5% nominal volumetric headroom" in text)

    tbl = _manifest_table(doc)
    check("manifest table header", tbl is not None)
    if tbl is not None:
        header = [c.text.strip() for c in tbl.rows[0].cells]
        check("table columns", header == ["Sequence", "Package ID",
              "Description", "Manifest", "Packed", "Weight/Unit",
              "Destination", "Fragile"], header)
        check("8 cargo rows", len(tbl.rows) == 9, len(tbl.rows))
        r1 = [c.text.strip() for c in tbl.rows[1].cells]
        check("row PKG-2001 fully populated", r1 == [
            "1", "PKG-2001", "Standard Shipping Cartons (Electronics)",
            "50", "50", "8.5 kg", "Boston", "—"], r1)
        check("fragile rows flagged Yes",
              all([c.text.strip() for c in tbl.rows[i].cells][7] == "Yes"
                  for i in (2, 5, 8)))
        check("handling instructions ignored",
              "Standard stackable" not in text
              and "Handle with care" not in text)
        check("partial-load row (3 of 7)",
              [c.text.strip() for c in tbl.rows[2].cells][4] == "3")
        last = [c.text.strip() for c in tbl.rows[8].cells]
        check("row PKG-2008", last[1] == "PKG-2008"
              and last[6] == "Charlotte" and last[7] == "Yes", last)

    check("unloading chain",
          "01  Boston   →   02  Atlanta" in text and "08  Charlotte" in text)
    check("utilization bar image embedded", len(doc.inline_shapes) == 1)

    path = os.path.join(out_dir, "verify_example_parity.docx")
    with open(path, "wb") as fh:
        fh.write(data)
    print(f"  -> wrote {path}")


def check_dock1_live(out_dir):
    print("\n2) DOCK-1 LIVE SHAPE (worker-imported manifest fields)")
    fleet = _dock1_fleet()
    data = build_invoice_docx(fleet, doc_id=invoice_doc_id(1, 1, now=FIXED_NOW))
    text, doc = _doc_text(data)

    check("dock 1 identity", "AX-D1-20260917-01" in text
          and "Dock 1" in text and "Truck-1" in text)
    check("live KPIs (69/69 packages, 691 kg, 16.0%)",
          "69 packages packed / 69 from manifest" in text
          and "691 kg" in text and "16.0%" in text)
    check("fragile via max_load heuristic (19)", "19" in text)
    check("non-fragile rows show —", "—" in text)
    check("no handling text anywhere",
          "handle with care" not in text.lower())

    tbl = _manifest_table(doc)
    check("manifest table present", tbl is not None)
    if tbl is not None:
        r1 = [c.text.strip() for c in tbl.rows[1].cells]
        check("live row: package id + destination captured",
              r1[1] == "PKG-1001" and r1[6] == "Rotterdam"
              and r1[7] == "—", r1)
        r2 = [c.text.strip() for c in tbl.rows[2].cells]
        check("live fragile row", r2[2] == "Glassware & Ceramics"
              and r2[1] == "PKG-1002" and r2[6] == "Oslo"
              and r2[7] == "Yes", r2)

    check("live unloading chain uses destination cities",
          "01  Rotterdam" in text and "02  Oslo" in text)

    path = os.path.join(out_dir, "verify_dock1_live.docx")
    with open(path, "wb") as fh:
        fh.write(data)
    print(f"  -> wrote {path}")


def main():
    # Pipe-safe emoji output on Windows consoles (cp1252 has no 🖨).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    print("=" * 70)
    print("VERIFY INVOICE — '🖨 Print Invoice' feature")
    print("=" * 70)
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "assets", "invoices")
    os.makedirs(out_dir, exist_ok=True)

    check_example_parity(out_dir)
    check_dock1_live(out_dir)

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"FAILED — {len(FAILURES)} check(s):")
        for f in FAILURES:
            print(f"  ✗ {f}")
        sys.exit(1)
    print("ALL CHECKS PASSED ✅")
    print("Open assets/invoices/*.docx in Word to eyeball the layout.")


if __name__ == "__main__":
    main()