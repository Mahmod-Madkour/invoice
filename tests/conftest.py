import pytest

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _isolated_settings_env(monkeypatch):
    """Tests never depend on the developer's environment (e.g. compose.dev.yml sets ENABLE_API_DOCS)."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
