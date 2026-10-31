import pytest
import requests
import responses

from stories_bot.telegram import TelegramApi, TelegramError

BASE = "https://api.telegram.org"


@responses.activate
def test_call_returns_the_result():
    responses.post(f"{BASE}/botSECRET/getMe", json={"ok": True, "result": {"id": 1}})
    assert TelegramApi("SECRET").call("getMe") == {"id": 1}


@responses.activate
def test_api_error_reports_status_and_description_without_the_token():
    responses.post(
        f"{BASE}/botSECRET/getFile",
        status=400,
        json={"ok": False, "description": "Bad Request: file is too big"},
    )
    with pytest.raises(TelegramError) as exc:
        TelegramApi("SECRET").call("getFile", {"file_id": "x"})
    assert "400" in str(exc.value) and "too big" in str(exc.value)
    assert "SECRET" not in str(exc.value)


@responses.activate
def test_non_json_answer_is_an_error():
    responses.post(f"{BASE}/botSECRET/getMe", status=502, body="<html>bad gateway</html>")
    with pytest.raises(TelegramError, match="HTTP 502: no details"):
        TelegramApi("SECRET").call("getMe")


@responses.activate
def test_network_error_does_not_leak_the_url():
    responses.post(
        f"{BASE}/botSECRET/getMe", body=requests.ConnectionError(f"failed {BASE}/botSECRET")
    )
    with pytest.raises(TelegramError) as exc:
        TelegramApi("SECRET").call("getMe")
    assert "ConnectionError" in str(exc.value) and "SECRET" not in str(exc.value)


@responses.activate
def test_download_returns_the_file_bytes():
    responses.get(f"{BASE}/file/botSECRET/documents/a.jpg", body=b"bytes")
    assert TelegramApi("SECRET").download("documents/a.jpg") == b"bytes"


@responses.activate
def test_download_failures_are_errors_without_the_token():
    responses.get(f"{BASE}/file/botSECRET/documents/a.jpg", status=404)
    with pytest.raises(TelegramError) as exc:
        TelegramApi("SECRET").download("documents/a.jpg")
    assert "404" in str(exc.value) and "SECRET" not in str(exc.value)

    responses.get(f"{BASE}/file/botSECRET/documents/b.jpg", body=requests.Timeout("slow"))
    with pytest.raises(TelegramError, match="Timeout"):
        TelegramApi("SECRET").download("documents/b.jpg")
