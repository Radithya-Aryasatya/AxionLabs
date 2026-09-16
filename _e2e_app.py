"""End-to-end harness: drive the real app.py through Streamlit's AppTest.

Exercises the Sardine-Can AI engine path (and the classic path as a control)
with an injected manifest, exactly the way a user would.

Run:  python _e2e_app.py     ->  writes _e2e_out.txt
"""
import io
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

OUT = []


def log(msg=""):
    OUT.append(str(msg))


MANIFEST = [
    {"name": "BoxA", "w": 0.6, "h": 0.5, "d": 0.4, "weight": 12.0,
     "quantity": 6, "max_load": float("inf"), "sequence": 1},
    {"name": "BoxB", "w": 0.4, "h": 0.4, "d": 0.4, "weight": 6.0,
     "quantity": 8, "max_load": float("inf"), "sequence": 2},
    {"name": "Fragile1", "w": 0.5, "h": 0.3, "d": 0.3, "weight": 3.0,
     "quantity": 4, "max_load": 3.0, "sequence": 3},
]
def run_case(engine_label, improve, prioritize):
    from streamlit.testing.v1 import AppTest

    log("=" * 72)
    log("CASE engine=%r improve=%r prioritize=%r"
        % (engine_label, improve, prioritize))
    log("=" * 72)

    at = AppTest.from_file(os.path.join(HERE, "app.py"), default_timeout=300)
    at.session_state["manifest"] = [dict(m) for m in MANIFEST]
    at.session_state["view_mode"] = "worker"
    at.run()

    if at.exception:
        log("!! unhandled exception during first run:")
        for exc in at.exception:
            log(str(getattr(exc, "value", exc)))
            log(str(getattr(exc, "message", "")))
        return False

    log("first run OK; sidebar radios=%d checkboxes=%d sliders=%d buttons=%d"
        % (len(at.sidebar.radio), len(at.sidebar.checkbox),
           len(at.sidebar.slider), len(at.button)))

    labels = [r.label for r in at.sidebar.radio]
    log("sidebar radios: %r" % (labels,))
    if "Packing Engine" not in labels:
        log("!! engine selector not found in sidebar")
        return False

    at.sidebar.radio(key="engine_choice").set_value(engine_label)

    cb_labels = [c.label for c in at.sidebar.checkbox]
    log("sidebar checkboxes: %r" % (cb_labels,))
    if engine_label == "Sardine-Can AI" and "AI Self-Improvement" not in cb_labels:
        log("!! AI Self-Improvement checkbox missing")
        return False

    for c in at.checkbox:
        if c.label.startswith("Prioritize unloading sequence"):
            c.set_value(prioritize)

    at.run()
    if at.exception:
        log("!! exception after selecting engine:")
        for exc in at.exception:
            log(str(getattr(exc, "value", exc)))
        return False

    run_btns = [b for b in at.button if "Run AI Optimization" in b.label]
    if not run_btns:
        log("!! Run button not found; buttons=%r"
            % ([b.label for b in at.button],))
        return False

    log("clicking %r ..." % run_btns[0].label)
    run_btns[0].click()
    at.run()

    if at.exception:
        log("!! exception during optimization:")
        log(traceback.format_exc())
        for exc in at.exception:
            log(str(getattr(exc, "value", exc)))
            log(str(getattr(exc, "message", "")))
        return False

    errs = [e.value for e in at.error]
    log("at.error: %r" % (errs,))
    if errs:
        log("!! the app reported errors")
        return False

    ss = at.session_state
    for key in ("sardine_solution", "sardine_hash", "sardine_improved",
                "ai_config", "ai_history", "ai_weights"):
        if key not in ss:
            log("  %s: <absent>" % key)
            continue
        val = ss[key]
        if key == "sardine_solution":
            log("  %s: packed=%d unfitted=%d engine=%s strategy=%s"
                % (key, len(val.packed), len(val.unfitted), val.engine,
                   val.strategy))
            log("      extra=%r" % (dict(val.extra),))
        elif key in ("ai_history", "ai_weights"):
            log("  %s: len=%d" % (key, len(val)))
        else:
            log("  %s: %r" % (key, val))

    return audit(at, ss)

def audit(at, ss):
    layouts = ss["layouts"] if "layouts" in ss else None
    if not layouts:
        log("!! no layout produced")
        return False

    best = layouts[0]
    log("best layout: packed=%d util=%.2f safety=%.2f offload=%.2f "
        "overall=%.2f floating=%d"
        % (len(best["packed"]), best["utilization"], best["safety"],
           best["offloading"], best["overall"], best["floating_count"]))

    lookup = {"%s #%d" % (m["name"], i + 1): m
              for m in ss["manifest"] for i in range(m["quantity"])}
    missing = []
    bad_dim = []
    oob = 0
    total = 0
    for b in best["packer"].bins:
        for item in b.items:
            total += 1
            if item.name not in lookup:
                missing.append(item.name)
                continue
            pos = item.position
            dim = item.getDimension()
            if (pos[0] < -1e-3 or pos[1] < -1e-3 or pos[2] < -1e-3 or
                    pos[0] + dim[0] > b.width + 1e-3 or
                    pos[1] + dim[1] > b.height + 1e-3 or
                    pos[2] + dim[2] > b.depth + 1e-3):
                oob += 1
            m = lookup[item.name]
            want = round(m["w"] * m["h"] * m["d"] * 1e6, 0)
            got = round(dim[0] * dim[1] * dim[2], 0)
            if got != want:
                bad_dim.append((item.name, dim, (m["w"], m["h"], m["d"])))

    log("geometry audit: items=%d missing_lookup=%d out_of_bounds=%d "
        "volume_mismatch=%d" % (total, len(missing), oob, len(bad_dim)))
    if missing:
        log("  missing: %r" % (missing[:10],))
    if bad_dim:
        log("  volume mismatch: %r" % (bad_dim[:5],))
    if oob or missing or bad_dim:
        log("!! geometry audit FAILED")
        return False

    bin0 = best["packer"].bins[0]
    log("bin0: partno=%r w=%s h=%s d=%s max_weight=%s put_type=%s gravity=%r"
        % (getattr(bin0, "partno", None), bin0.width, bin0.height, bin0.depth,
           bin0.max_weight, getattr(bin0, "put_type", None),
           getattr(bin0, "gravity", None)))

    log("CASE PASSED")
    return True


def main():
    ok = True
    for label, improve, prio in (("Sardine-Can AI", True, False),
                                 ("Sardine-Can AI", False, True),
                                 ("Classic (py3dbp)", False, False)):
        try:
            ok &= run_case(label, improve, prio)
        except Exception:  # noqa: BLE001
            log("!! harness crash:")
            log(traceback.format_exc())
            ok = False

    log("")
    log("=== RESULT: %s ==="
        % ("ALL E2E CHECKS PASSED" if ok else "FAILURES"))

    text = "\n".join(OUT) + "\n"
    with io.open(os.path.join(HERE, "_e2e_out.txt"), "w",
                 encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

