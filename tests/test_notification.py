from unittest.mock import MagicMock

import pytest
import requests

import notification


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "tok-123")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "user-abc")


def test_posts_to_pushover_with_credentials_and_message(creds, monkeypatch):
    mock_post = MagicMock()
    monkeypatch.setattr(notification.requests, "post", mock_post)

    result = notification.push("hello world")

    assert result is None
    mock_post.assert_called_once_with(
        "https://api.pushover.net/1/messages.json",
        data={"token": "tok-123", "user": "user-abc", "message": "hello world"},
        timeout=5,
    )


def test_noop_when_token_missing(monkeypatch):
    monkeypatch.delenv("PUSHOVER_API_TOKEN", raising=False)
    monkeypatch.setenv("PUSHOVER_USER_KEY", "user-abc")
    mock_post = MagicMock()
    monkeypatch.setattr(notification.requests, "post", mock_post)

    notification.push("hi")

    mock_post.assert_not_called()


def test_noop_when_user_key_missing(monkeypatch):
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "tok-123")
    monkeypatch.delenv("PUSHOVER_USER_KEY", raising=False)
    mock_post = MagicMock()
    monkeypatch.setattr(notification.requests, "post", mock_post)

    notification.push("hi")

    mock_post.assert_not_called()


def test_noop_when_token_empty_string(monkeypatch):
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "user-abc")
    mock_post = MagicMock()
    monkeypatch.setattr(notification.requests, "post", mock_post)

    notification.push("hi")

    mock_post.assert_not_called()


def test_swallows_request_exception(creds, monkeypatch):
    def boom(*args, **kwargs):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(notification.requests, "post", boom)

    assert notification.push("hi") is None


def test_does_not_swallow_unexpected_exceptions(creds, monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("not a request error")

    monkeypatch.setattr(notification.requests, "post", boom)

    with pytest.raises(ValueError):
        notification.push("hi")
