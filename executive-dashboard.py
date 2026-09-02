"""
executive-dashboard.py  [LEGACY ENTRY POINT]
=============================================
The canonical View 2 controller is `executive_dashboard.py` (underscore name,
importable as a module). This hyphenated file is kept only as a convenience
legacy entry point so `streamlit run executive-dashboard.py` still works.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from state.fleet_state import initialize_session_state
from components.header import render_header
from executive_dashboard import render_executive_dashboard

initialize_session_state()
render_header()
render_executive_dashboard()

