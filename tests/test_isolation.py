"""The suite must never read the settings of whoever runs it."""
from amanuense import settings


def test_the_suite_never_reads_the_users_own_settings(tmp_path_factory):
    assert settings.config_dir().is_relative_to(tmp_path_factory.getbasetemp())
