from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import guardrails
from guardrails import (
    ChatRequest,
    HistoryTurn,
    client_ip,
    require_internal_key,
    truncate_history,
)


# ---------- client_ip ----------


def _request_with_headers(headers: dict) -> MagicMock:
    req = MagicMock()
    req.headers.get.side_effect = lambda key, default=None: headers.get(key, default)
    return req


def test_client_ip_returns_first_forwarded_for_value():
    req = _request_with_headers({"x-forwarded-for": "203.0.113.5, 10.0.0.1"})
    assert client_ip(req) == "203.0.113.5"


def test_client_ip_strips_whitespace_around_forwarded_value():
    req = _request_with_headers({"x-forwarded-for": "  203.0.113.5  "})
    assert client_ip(req) == "203.0.113.5"


def test_client_ip_falls_back_to_remote_address_when_no_xff(monkeypatch):
    monkeypatch.setattr(guardrails, "get_remote_address", lambda r: "198.51.100.7")
    req = _request_with_headers({})
    assert client_ip(req) == "198.51.100.7"


def test_client_ip_falls_back_to_remote_address_when_xff_is_empty_string(monkeypatch):
    monkeypatch.setattr(guardrails, "get_remote_address", lambda r: "198.51.100.7")
    req = _request_with_headers({"x-forwarded-for": ""})
    assert client_ip(req) == "198.51.100.7"


# ---------- HistoryTurn ----------


def test_history_turn_accepts_user_and_assistant_roles():
    assert HistoryTurn(role="user", content="hi").role == "user"
    assert HistoryTurn(role="assistant", content="hi").role == "assistant"


def test_history_turn_rejects_invalid_role():
    with pytest.raises(ValidationError):
        HistoryTurn(role="system", content="hi")


def test_history_turn_rejects_empty_content():
    with pytest.raises(ValidationError):
        HistoryTurn(role="user", content="")


def test_history_turn_rejects_content_over_max_length():
    with pytest.raises(ValidationError):
        HistoryTurn(role="user", content="x" * 4001)


def test_history_turn_accepts_single_char_content():
    assert HistoryTurn(role="user", content="x").content == "x"


def test_history_turn_accepts_content_at_max_length():
    content = "x" * 4000
    assert HistoryTurn(role="user", content=content).content == content


# ---------- ChatRequest ----------


def test_chat_request_strips_message_whitespace():
    req = ChatRequest(message="   hello   ")
    assert req.message == "hello"


def test_chat_request_rejects_whitespace_only_message():
    with pytest.raises(ValidationError):
        ChatRequest(message="   ")


def test_chat_request_rejects_empty_message():
    with pytest.raises(ValidationError):
        ChatRequest(message="")


def test_chat_request_rejects_message_over_max_length():
    with pytest.raises(ValidationError):
        ChatRequest(message="x" * (guardrails.MAX_MESSAGE_LENGTH + 1))


def test_chat_request_accepts_message_at_max_length():
    msg = "x" * guardrails.MAX_MESSAGE_LENGTH
    assert ChatRequest(message=msg).message == msg


def test_chat_request_defaults_history_to_empty_list():
    req = ChatRequest(message="hi")
    assert req.history == []


# ---------- truncate_history ----------


def test_truncate_history_keeps_only_last_n_turns():
    turns = [HistoryTurn(role="user", content=f"m{i}") for i in range(guardrails.MAX_HISTORY_TURNS + 5)]
    result = truncate_history(turns)
    assert len(result) == guardrails.MAX_HISTORY_TURNS
    assert result[0]["content"] == f"m{5}"
    assert result[-1]["content"] == f"m{guardrails.MAX_HISTORY_TURNS + 4}"


def test_truncate_history_passes_through_when_under_limit():
    turns = [
        HistoryTurn(role="user", content="a"),
        HistoryTurn(role="assistant", content="b"),
    ]
    assert truncate_history(turns) == [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]


def test_truncate_history_handles_empty_list():
    assert truncate_history([]) == []


def test_truncate_history_passes_through_at_exactly_limit():
    turns = [HistoryTurn(role="user", content=f"m{i}") for i in range(guardrails.MAX_HISTORY_TURNS)]
    result = truncate_history(turns)
    assert len(result) == guardrails.MAX_HISTORY_TURNS
    assert result[0]["content"] == "m0"


def test_truncate_history_drops_oldest_when_one_over_limit():
    turns = [HistoryTurn(role="user", content=f"m{i}") for i in range(guardrails.MAX_HISTORY_TURNS + 1)]
    result = truncate_history(turns)
    assert len(result) == guardrails.MAX_HISTORY_TURNS
    assert result[0]["content"] == "m1"


# ---------- require_internal_key ----------


async def test_require_internal_key_returns_500_when_env_missing(monkeypatch):
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    with pytest.raises(HTTPException) as exc:
        await require_internal_key(x_internal_key="anything")
    assert exc.value.status_code == 500


async def test_require_internal_key_returns_500_when_env_empty_string(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "")
    with pytest.raises(HTTPException) as exc:
        await require_internal_key(x_internal_key="anything")
    assert exc.value.status_code == 500


async def test_require_internal_key_returns_401_when_header_missing(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "secret")
    with pytest.raises(HTTPException) as exc:
        await require_internal_key(x_internal_key=None)
    assert exc.value.status_code == 401


async def test_require_internal_key_returns_401_when_header_wrong(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "secret")
    with pytest.raises(HTTPException) as exc:
        await require_internal_key(x_internal_key="wrong")
    assert exc.value.status_code == 401


async def test_require_internal_key_passes_when_header_matches(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "secret")
    assert await require_internal_key(x_internal_key="secret") is None
