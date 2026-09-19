import copy

import pytest

from factory import settings


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Run a test against a throwaway repo root.

    Patching ROOT alone is not enough: settings.load() is cached and reads
    config.toml relative to ROOT, so it would either return the real settings or
    fail looking for a config that is not there. Read the real config first,
    then point both at the temporary directory.
    """
    raw = copy.deepcopy(settings.load().raw)
    monkeypatch.setattr(settings, "ROOT", tmp_path)
    fake = settings.Settings(raw)
    monkeypatch.setattr(settings, "load", lambda: fake)
    settings.load_env.cache_clear()
    return tmp_path
