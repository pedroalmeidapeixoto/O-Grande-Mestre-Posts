import pytest
import responses

from stories_bot import ig_token
from stories_bot.config import ConfigError, Settings
from stories_bot.instagram import API_URLS, INSTAGRAM_LOGIN_URL, InstagramClient

EXCHANGE = "https://graph.instagram.com/access_token"
REFRESH = "https://graph.instagram.com/refresh_access_token"
ME = "https://graph.instagram.com/v21.0/me"


@responses.activate
def test_exchange_refresh_and_whoami():
    responses.get(EXCHANGE, json={"access_token": "long", "expires_in": 5183944})
    responses.get(REFRESH, json={"access_token": "renewed", "expires_in": 5184000})
    responses.get(ME, json={"user_id": "1784", "id": "app-scoped", "username": "loja"})

    assert ig_token.exchange_for_long_lived("secret", "short") == ("long", 59)
    assert ig_token.refresh("long") == ("renewed", 60)
    assert ig_token.whoami("long") == ("1784", "loja")


@responses.activate
def test_api_errors_become_token_errors_without_the_token():
    responses.get(REFRESH, status=400, json={"error": {"message": "too new"}})
    with pytest.raises(ig_token.TokenError, match="too new") as err:
        ig_token.refresh("tok-123")
    assert "tok-123" not in str(err.value)


@responses.activate
def test_main_exchanges_when_given_a_secret(monkeypatch, capsys):
    responses.get(EXCHANGE, json={"access_token": "long", "expires_in": 5183944})
    responses.get(ME, json={"user_id": "1784", "username": "loja"})
    answers = iter(["short", "app-secret"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    assert ig_token.main() == 0
    out = capsys.readouterr().out
    assert "@loja  ->  IG_USER_ID = 1784" in out and "long" in out and "IG_API" in out


@responses.activate
def test_main_keeps_the_token_when_it_cannot_be_extended(monkeypatch, capsys):
    responses.get(REFRESH, status=400, json={"error": {"message": "too new"}})
    responses.get(ME, json={"id": "1784", "username": "loja"})
    answers = iter(["tok", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    assert ig_token.main() == 0
    assert "using it as it is" in capsys.readouterr().out


@responses.activate
def test_main_fails_on_a_rejected_token(monkeypatch):
    responses.get(REFRESH, status=400, json={})
    responses.get(ME, status=400, json={"error": {"message": "bad"}})
    answers = iter(["tok", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert ig_token.main() == 1


def test_ig_api_setting_selects_the_host():
    base = {"IG_USER_ID": "1", "IG_ACCESS_TOKEN": "t", "MEDIA_BASE_URL": "https://h/media"}
    assert Settings.from_env(base).ig_api == "facebook"
    assert Settings.from_env({**base, "IG_API": " Instagram "}).ig_api == "instagram"
    with pytest.raises(ConfigError, match="IG_API"):
        Settings.from_env({**base, "IG_API": "tiktok"})


def test_ig_api_is_guessed_from_the_token_when_unset():
    ids = {"IG_USER_ID": "1", "MEDIA_BASE_URL": "https://h/media"}
    assert Settings.from_env({**ids, "IG_ACCESS_TOKEN": "IGAAxyz"}).ig_api == "instagram"
    assert Settings.from_env({**ids, "IG_ACCESS_TOKEN": "EAAxyz"}).ig_api == "facebook"
    explicit = {**ids, "IG_ACCESS_TOKEN": "IGAAxyz", "IG_API": "facebook"}
    assert Settings.from_env(explicit).ig_api == "facebook"  # explicit wins


@responses.activate
def test_client_publishes_through_the_instagram_login_host():
    responses.post(f"{INSTAGRAM_LOGIN_URL}/17841/media", json={"id": "c1"})
    responses.get(f"{INSTAGRAM_LOGIN_URL}/c1", json={"status_code": "FINISHED"})
    responses.post(f"{INSTAGRAM_LOGIN_URL}/17841/media_publish", json={"id": "m1"})

    client = InstagramClient("17841", "tok", base_url=API_URLS["instagram"], sleep=lambda _: None)
    assert client.publish_story("https://cdn.example/a.jpg", is_video=False) == "m1"
