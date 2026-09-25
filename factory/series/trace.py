"""Traces: enough of a finished simulation to redraw any frame without it.

`trace.npz` holds the arrays, `trace.json` the rest. Both are written
deterministically — sorted names, fixed zip timestamps, sorted JSON keys — so
the same seed, spec and code give byte-identical files, which is how a test
proves a race is reproducible.

Redrawing is the generator's job (`Generator.redraw`), reached through the
registry: this module stores and loads, and never imports a generator.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA_VERSION = 1
NPZ = "trace.npz"
JSON = "trace.json"
_EPOCH = (1980, 1, 1, 0, 0, 0)


def write(directory: Path, arrays: dict[str, np.ndarray], meta: dict[str, Any]) -> Path:
    """Write trace.npz and trace.json into `directory`; return the json path."""
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(directory / NPZ, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(arrays):
            buf = io.BytesIO()
            np.lib.format.write_array(buf, np.ascontiguousarray(arrays[name]), allow_pickle=False)
            info = zipfile.ZipInfo(f"{name}.npy", date_time=_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, buf.getvalue())
    body = {"schema_version": SCHEMA_VERSION, **meta}
    path = directory / JSON
    path.write_text(json.dumps(body, sort_keys=True, indent=1, default=_plain) + "\n")
    return path


def read(where: Path) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Load a trace from its directory or from its trace.json path."""
    directory = where.parent if where.name == JSON else where
    meta = json.loads((directory / JSON).read_text())
    if meta.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"trace schema {meta.get('schema_version')} is not {SCHEMA_VERSION}: {directory}")
    with np.load(directory / NPZ, allow_pickle=False) as npz:
        arrays = {name: npz[name] for name in npz.files}
    return arrays, meta


def _plain(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    raise TypeError(f"not serialisable in a trace: {type(value).__name__}")
