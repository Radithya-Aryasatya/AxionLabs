How to swap a dock's cargo (VSCODE only — nothing to click in the app)
====================================================================

1. In VSCODE, open the `dock_manifests/` folder.
2. To update a dock, OVERWRITE its file with your newer Excel:
     Dock 2 -> `dock2_manifest.xlsx`
     Dock 3 -> `dock3_manifest.xlsx`
     Dock 4 -> `dock4_manifest.xlsx` (optional; absent = placeholder stays)
   Keep the FILE NAME the same. Keep the COLUMN NAMES the same:
     Package ID | Tracking Number | Item Description | Box Quantity |
     Box Weight (kg) | Length (cm) | Width (cm) | Height (cm) | Fragile |
     Handling Instructions | Storage Zone | Unloading Sequence |
     Destination City
   Sheet rule: the `Dock 2 - Demo` sheet is used when present,
   otherwise the first sheet.
3. Refresh the Streamlit app (or press "Reset Mock Docks" once under
   Demo Controls). The app notices the Excel changed and rebuilds that
   dock's 3D twin automatically. All docks share the Dock-1 truck:
   2.4 x 2.4 x 6.0 m.

If an Excel is missing or broken, the dock keeps its last good layout
and a warning is printed to the terminal (the dashboard never crashes).
