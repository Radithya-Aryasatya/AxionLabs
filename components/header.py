import streamlit as st
from state.fleet_state import initialize_session_state


def render_header():
    """Render the persistent top navigation header with centered view toggle."""
    initialize_session_state()

    # Inject custom CSS for the toggle switch and header styling
    st.markdown(
        """
        <style>
        /* Hide the default Streamlit header */
        [data-testid="stToolbar"],
        header { visibility: hidden; }
        .main { padding-top: 0px; }

        /* Header container */
        .axion-header {
            display: flex;
            align-items: center;
            justify-content: center;
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
    """,
        unsafe_allow_html=True,
    )

    # Use symmetrical outer columns to horizontally center the toggle buttons
    left_spacer, toggle_col, right_spacer = st.columns([1, 2, 1])

    with toggle_col:
        current_mode = st.session_state.get("view_mode", "worker")

        # Two equal inner columns for the buttons
        col_a, col_b = st.columns(2, gap="small")

        with col_a:
            worker_selected = current_mode == "worker"
            if st.button(
                "Worker / Planner",
                key="toggle_worker",
                type="primary" if worker_selected else "secondary",
                use_container_width=True,
            ):
                st.session_state.view_mode = "worker"
                st.rerun()

        with col_b:
            exec_selected = current_mode == "executive"
            if st.button(
                "Executive / Manager",
                key="toggle_executive",
                type="primary" if exec_selected else "secondary",
                use_container_width=True,
            ):
                st.session_state.view_mode = "executive"
                st.rerun()

    st.markdown("---")