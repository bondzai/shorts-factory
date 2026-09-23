"""The console's web server.

The routes moved into `factory.api`, one module per screen; this is the name
the rest of the code (and every test) already imports.
"""

from __future__ import annotations

from .api import JOB, app, serve  # noqa: F401
from .api.common import download_name  # noqa: F401

__all__ = ["JOB", "app", "download_name", "serve"]
