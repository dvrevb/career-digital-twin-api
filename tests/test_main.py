import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIError, APITimeoutError

import main


@pytest.fixture(autouse=True)
def _internal_key(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "test-secret")


@pytest.fixture
def mock_me(monkeypatch):
    me = AsyncMock()
    me.chat_async = AsyncMock(return_value=("hi back", 7, "gpt-test"))
    monkeypatch.setattr(main, "_me", me)
    return me


@pytest.fixture
def client(mock_me):
    return TestClient(main.app)


def _httpx_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


# ---------- /health ----------


def test_health_reports_ok_and_openai_key_state(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with TestClient(main.app) as c:
        resp = c.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "openai_key_present": True}


def test_health_reports_false_when_openai_key_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(main.app) as c:
        resp = c.get("/health")
    assert resp.json()["openai_key_present"] is False


# ---------- /chat happy path ----------


def test_chat_happy_path_returns_reply_tokens_and_model(client, mock_me):
    resp = client.post(
        "/chat",
        headers={"X-Internal-Key": "test-secret"},
        json={"message": "hello"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"reply": "hi back", "tokens_used": 7, "model": "gpt-test"}
    mock_me.chat_async.assert_awaited_once()


def test_chat_passes_truncated_history_to_agent(client, mock_me, monkeypatch):
    monkeypatch.setattr(main, "MAX_HISTORY_TURNS", 10, raising=False)
    history = [{"role": "user", "content": f"m{i}"} for i in range(15)]
    history += [{"role": "assistant", "content": "ok"}]
    client.post(
        "/chat",
        headers={"X-Internal-Key": "test-secret"},
        json={"message": "hello", "history": history},
    )
    args, _ = mock_me.chat_async.call_args
    passed_message, passed_history = args
    assert passed_message == "hello"
    assert len(passed_history) == 10  # MAX_HISTORY_TURNS default


# ---------- /chat auth ----------


def test_chat_returns_401_when_internal_key_missing(client):
    resp = client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 401


def test_chat_returns_401_when_internal_key_wrong(client):
    resp = client.post(
        "/chat",
        headers={"X-Internal-Key": "wrong"},
        json={"message": "hello"},
    )
    assert resp.status_code == 401


# ---------- /chat validation (422 → 400 rewrite) ----------


def test_chat_returns_400_for_empty_message(client):
    resp = client.post(
        "/chat",
        headers={"X-Internal-Key": "test-secret"},
        json={"message": ""},
    )
    assert resp.status_code == 400


def test_chat_returns_400_for_whitespace_only_message(client):
    resp = client.post(
        "/chat",
        headers={"X-Internal-Key": "test-secret"},
        json={"message": "   "},
    )
    assert resp.status_code == 400


def test_chat_returns_400_for_missing_message_field(client):
    resp = client.post(
        "/chat",
        headers={"X-Internal-Key": "test-secret"},
        json={"history": []},
    )
    assert resp.status_code == 400


def test_chat_returns_400_for_message_over_max_length(client):
    from guardrails import MAX_MESSAGE_LENGTH

    resp = client.post(
        "/chat",
        headers={"X-Internal-Key": "test-secret"},
        json={"message": "x" * (MAX_MESSAGE_LENGTH + 1)},
    )
    assert resp.status_code == 400


def test_chat_returns_400_for_invalid_history_role(client):
    resp = client.post(
        "/chat",
        headers={"X-Internal-Key": "test-secret"},
        json={
            "message": "hi",
            "history": [{"role": "system", "content": "should fail"}],
        },
    )
    assert resp.status_code == 400


# ---------- /chat upstream errors ----------


def test_chat_returns_504_on_asyncio_timeout(client, mock_me):
    mock_me.chat_async.side_effect = asyncio.TimeoutError()
    resp = client.post(
        "/chat",
        headers={"X-Internal-Key": "test-secret"},
        json={"message": "hello"},
    )
    assert resp.status_code == 504
    assert resp.json()["detail"] == "upstream timeout"


def test_chat_returns_504_on_openai_timeout(client, mock_me):
    mock_me.chat_async.side_effect = APITimeoutError(request=_httpx_request())
    resp = client.post(
        "/chat",
        headers={"X-Internal-Key": "test-secret"},
        json={"message": "hello"},
    )
    assert resp.status_code == 504
    assert resp.json()["detail"] == "openai timeout"


def test_chat_returns_502_on_openai_api_error(client, mock_me):
    mock_me.chat_async.side_effect = APIError(
        "boom", request=_httpx_request(), body=None
    )
    resp = client.post(
        "/chat",
        headers={"X-Internal-Key": "test-secret"},
        json={"message": "hello"},
    )
    assert resp.status_code == 502
    assert resp.json()["detail"] == "upstream error"


# ---------- get_me lazy singleton ----------


def test_get_me_caches_instance_after_first_call(monkeypatch):
    monkeypatch.setattr(main, "_me", None)
    sentinel = object()
    monkeypatch.setattr(main, "Me", lambda: sentinel)

    first = main.get_me()
    second = main.get_me()
    assert first is sentinel
    assert second is sentinel
