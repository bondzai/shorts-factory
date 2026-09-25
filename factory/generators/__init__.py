"""Generator slot. Importing this package registers every module in it."""

from .base import (  # noqa: F401
    GeneratedClip,
    Generator,
    all_generators,
    available,
    catalogue,
    get,
    ready_generators,
    register,
)

from . import physics  # noqa: F401,E402
from . import battle  # noqa: F401,E402
