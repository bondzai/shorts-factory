import os

import pytest

from factory import settings


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ROOT", tmp_path)
    settings.load_env.cache_clear()
    yield tmp_path / ".env"
    settings.load_env.cache_clear()


def test_missing_file_is_fine(env_file):
    assert settings.load_env() == 0


def test_values_are_loaded(env_file, monkeypatch):
    monkeypatch.delenv("SHORTS_FACTORY_TEST", raising=False)
    env_file.write_text("SHORTS_FACTORY_TEST=hello\n")
    assert settings.load_env() == 1
    assert os.environ["SHORTS_FACTORY_TEST"] == "hello"


def test_a_real_environment_variable_wins(env_file, monkeypatch):
    monkeypatch.setenv("SHORTS_FACTORY_TEST", "from-shell")
    env_file.write_text("SHORTS_FACTORY_TEST=from-file\n")
    assert settings.load_env() == 0
    assert os.environ["SHORTS_FACTORY_TEST"] == "from-shell"


def test_comments_blanks_and_quotes(env_file, monkeypatch):
    monkeypatch.delenv("SHORTS_FACTORY_QUOTED", raising=False)
    env_file.write_text(
        "# a comment\n\nnot_a_pair\nSHORTS_FACTORY_QUOTED='sk-test-value'\n"
    )
    assert settings.load_env() == 1
    assert os.environ["SHORTS_FACTORY_QUOTED"] == "sk-test-value"
