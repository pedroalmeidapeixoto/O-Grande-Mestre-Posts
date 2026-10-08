from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stories_bot.config import ConfigError, Settings, media_url
from stories_bot.state import load_posted, record_post

BASE = {"IG_USER_ID": "1", "IG_ACCESS_TOKEN": "t"}


def test_settings_from_explicit_media_url():
    s = Settings.from_env({**BASE, "MEDIA_BASE_URL": "https://cdn.example/media"})
    assert (s.ig_user_id, s.ig_access_token) == ("1", "t")
    assert s.media_base_url == "https://cdn.example/media"


def test_settings_derive_media_url_from_github_actions():
    env = {**BASE, "GITHUB_REPOSITORY": "owner/repo", "GITHUB_REF_NAME": "main"}
    assert Settings.from_env(env).media_base_url == (
        "https://raw.githubusercontent.com/owner/repo/main/media"
    )


def test_settings_report_every_missing_variable():
    with pytest.raises(ConfigError) as exc:
        Settings.from_env({})
    for name in ("IG_USER_ID", "IG_ACCESS_TOKEN", "MEDIA_BASE_URL"):
        assert name in str(exc.value)


def test_media_url_quotes_filenames():
    assert (
        media_url("https://h/media/", "prato do dia.jpg") == "https://h/media/prato%20do%20dia.jpg"
    )


def test_state_roundtrip_and_missing_file(tmp_path):
    path = tmp_path / "state" / "posted.json"
    assert load_posted(path) == {}

    when = datetime(2026, 10, 9, 18, 5, tzinfo=ZoneInfo("America/Sao_Paulo"))
    record_post(path, "k1", "m1", when)
    record_post(path, "k2", "m2", when)

    posted = load_posted(path)
    assert set(posted) == {"k1", "k2"}
    assert posted["k1"]["media_id"] == "m1"
    assert not path.with_suffix(".tmp").exists()
