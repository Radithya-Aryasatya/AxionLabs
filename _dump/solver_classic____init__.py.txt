"""
solver_classic
==============
Thin adapter that wraps the *existing* py3dbp code path in
``AxionLabs/app.py``.

This engine preserves **byte-for-byte** the behaviour the app had before the
solver abstraction was introduced.  It is used when the user selects
"Classic (py3dbp)" — the default engine that has always been here.
"""
from .adapter import solve  # noqa: F401

__all__ = ["solve"]
