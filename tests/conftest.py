import copy

import pytest

from factory import settings


@pytest.fixture(autouse=True)
def no_door(monkeypatch):
    """No test signs in by accident. The machine's .env may hold the operator's
    password or PIN, and load_env never overrides a variable already set, so
    an empty one keeps every test's door open unless the test sets its own."""
    monkeypatch.setenv("FACTORY_PASSWORD", "")
    monkeypatch.setenv("FACTORY_PIN", "")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Run a test against a throwaway repo root.

    Patching ROOT alone is not enough: settings.load() is cached and reads
    config.toml relative to ROOT, so it would either return the real settings or
    fail looking for a config that is not there. Read the real config first,
    then point both at the temporary directory.
    """
    # config.toml alone: the operator's overrides live in this machine's
    # database, and a test that read them (rounds = 1 set on Settings) passed
    # on one machine and failed on another.
    raw = copy.deepcopy(settings.load().base)
    monkeypatch.setattr(settings, "ROOT", tmp_path)
    # base is config.toml alone; the page shows it as the default under an override.
    fake = settings.Settings(raw, base=copy.deepcopy(raw))
    monkeypatch.setattr(settings, "load", lambda: fake)
    settings.load_env.cache_clear()
    return tmp_path
