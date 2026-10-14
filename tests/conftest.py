"""The original suites describe the Spanish workshop; test_i18n covers the English default."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amanuense import i18n  # noqa: E402


@pytest.fixture(autouse=True)
def _workshop_language(request, monkeypatch):
    lang = "en" if request.module.__name__.endswith("test_i18n") else "es"
    if lang == "es":
        monkeypatch.setenv("AMANUENSE_LANG", "es")
    else:
        monkeypatch.delenv("AMANUENSE_LANG", raising=False)
    i18n.use(lang)
    yield
    i18n.use(i18n.DEFAULT)
