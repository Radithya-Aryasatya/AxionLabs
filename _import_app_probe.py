"""Temporary: check whether app.py can be imported outside `streamlit run`."""
import io
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

out = []
try:
    import app  # noqa: F401
    out.append("IMPORT OK")
    out.append("has PackedItem       : %s" % hasattr(app, "PackedItem"))
    out.append("has calculate_util   : %s" % hasattr(app, "calculate_utilization"))
    out.append("has load_distribution: %s" % hasattr(app, "calculate_load_distribution"))
    out.append("has detect_floating  : %s" % hasattr(app, "detect_floating_items"))
    out.append("has offloading_score : %s" % hasattr(app, "calculate_offloading_score"))
    out.append("has pack_soft_lifo   : %s" % hasattr(app, "pack_soft_lifo"))
    out.append("has overlap_area     : %s" % hasattr(app, "calculate_overlap_area"))
except BaseException as e:  # noqa: BLE001
    out.append("IMPORT FAILED: %r" % (e,))
    out.append(traceback.format_exc())

text = "\n".join(out)
io.open(os.path.join(HERE, "_import_app_out.txt"), "w", encoding="utf-8").write(text + "\n")
sys.stdout.write(text.encode("ascii", "replace").decode("ascii") + "\n")