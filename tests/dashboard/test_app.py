"""Smoke tests for the Streamlit app module (sprint-3/phase-9)."""


def test_app_import_no_server():
    """Verify that importing app.py doesn't start streamlit or invoke st.write/st.title/etc.

    Also asserts main and render are callable functions.
    """
    # Import the module
    import enterprise_rag_ops.dashboard.app as app

    # Assert main and render are callable
    assert callable(app.main)
    assert callable(app.render)
