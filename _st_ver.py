"""Report the installed Streamlit version + AppTest availability."""
import io
import os

out = []
try:
    import streamlit as st
    out.append("streamlit %s" % st.__version__)
except Exception as exc:  # noqa: BLE001
    out.append("streamlit IMPORT FAIL: %r" % (exc,))

try:
    from streamlit.testing.v1 import AppTest
    out.append("AppTest available: %s" % AppTest)
except Exception as exc:  # noqa: BLE001
    out.append("AppTest unavailable: %r" % (exc,))

for name in ("py3dbp", "pandas", "plotly"):
    try:
        mod = __import__(name)
        out.append("%s %s" % (name, getattr(mod, "__version__", "?")))
    except Exception as exc:  # noqa: BLE001
        out.append("%s IMPORT FAIL: %r" % (name, exc))

text = "\n".join(out) + "\n"
io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "_st_ver_out.txt"), "w", encoding="utf-8").write(text)
print(text)
