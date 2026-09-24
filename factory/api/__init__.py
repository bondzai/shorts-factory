"""The console's HTTP surface: one router per screen, assembled in `server`."""

from .common import JOB  # noqa: F401
from .server import app, serve  # noqa: F401
