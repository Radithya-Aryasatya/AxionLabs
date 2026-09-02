"""
components/header.py
=====================
Top navigation bar with the View Toggle Switch.
Renders a persistent header that allows switching between:
  - [ View 1 ] Loading Planner (Worker/Gudang)
  - [ View 2 ] Executive Control Tower (Manager)
"""

import streamlit as st
from state.fleet_state import initialize_session_state


def render_header():
    """
    Render the persistent top navigation header with view toggle.
    This should be called at the very top of app.py.
    """
    initialize_session_state()

    # Inject custom CSS for the toggle switch and header styling
    st.markdown("""
        <style>
        /* Hide the default Streamlit header */
        [data-testid="stToolbar"],
        header { visibility: hidden; }
        .main { padding-top: 0px; }

        /* Header container */
        .axion-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 24px;
            background: linear-gradient(135deg, #1e293b 0%, #334159 100%);
            border-bottom: 3px solid #3B82F6;
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .axion-logo {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .axion-logo h2 {
            margin: 0;
            font-size: 18px;
            font-weight: 700;
            color: #ffffff;
        }
        .axion-logo .badge {
            font-size: 10px;
            background: #F59E0B;
            color: #000;
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 700;
        }

        /* Toggle switch styling */
        .view-toggle {
            display: flex;
            align-items: center;
            gap: 4px;
            background: #475569;
            border-radius: 24px;
            padding: 4px 8px;
            cursor: pointer;
            transition: all 0.2s ease;
            user-select: none;
        }
        .view-toggle:hover {
            background: #64748b;
        }
        .view-toggle.active {
            background: #0F172A;
        }

        .view-option {
            padding: 4px 14px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            color: #94A3B8;
            transition: all 0.2s ease;
            white-space: nowrap;
        }
        .view-option.active {
            background: #3B82F6;
            color: #ffffff;
        }
        </style>
    """, unsafe_allow_html=True)

    # Render the header
    _, logo_col, toggle_col = st.columns([0.15, 0.3, 0.55])

    with logo_col:
        st.markdown("""
            <div class="axion-header-logo">
                <h2>🚛 AxionLabs FleetOps</h2>
            </div>
        """, unsafe_allow_html=True)

    with toggle_col:
        # Use a radio button but style it as a toggle switch
        current_mode = st.session_state.get('view_mode', 'worker')

        # Create the toggle using columns for visual layout
        col_a, col_b = st.columns(2, gap="small")

        with col_a:
            worker_selected = current_mode == 'worker'
            btn_key = "toggle_worker"
            if st.button(
                "Worker / Planner",
                key=btn_key,
                type="primary" if worker_selected else "secondary",
                width='stretch',
            ):
                st.session_state.view_mode = 'worker'
                st.rerun()

        with col_b:
            exec_selected = current_mode == 'executive'
            if st.button(
                "Executive / Manager",
                key="toggle_executive",
                type="primary" if exec_selected else "secondary",
                width='stretch',
            ):
                st.session_state.view_mode = 'executive'
                st.rerun()

    st.markdown("---")
