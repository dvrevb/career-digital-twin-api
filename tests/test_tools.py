from unittest.mock import MagicMock

import pytest

import tools
from tools import (
    record_unknown_question,
    record_user_details,
    record_unknown_question_json,
    record_user_details_json,
)


@pytest.fixture
def mock_push(monkeypatch):
    push = MagicMock()
    monkeypatch.setattr(tools, "push", push)
    return push


def test_record_user_details_pushes_full_message_and_returns_ok(mock_push):
    result = record_user_details(
        email="alice@example.com", name="Alice", notes="met at conf"
    )
    assert result == {"recorded": "ok"}
    mock_push.assert_called_once_with(
        "Recording Alice with email alice@example.com and notes met at conf"
    )


def test_record_user_details_uses_defaults_when_only_email_given(mock_push):
    result = record_user_details(email="bob@example.com")
    assert result == {"recorded": "ok"}
    mock_push.assert_called_once_with(
        "Recording Name not provided with email bob@example.com and notes not provided"
    )


def test_record_user_details_default_only_for_omitted_fields(mock_push):
    record_user_details(email="c@example.com", name="Carol")
    mock_push.assert_called_once_with(
        "Recording Carol with email c@example.com and notes not provided"
    )


def test_record_unknown_question_pushes_and_returns_ok(mock_push):
    result = record_unknown_question(question="what's your favorite framework?")
    assert result == {"recorded": "ok"}
    mock_push.assert_called_once_with("Recording what's your favorite framework?")


def test_tool_schemas_match_function_signatures():
    assert record_user_details_json["name"] == "record_user_details"
    assert record_user_details_json["parameters"]["required"] == ["email"]
    assert set(record_user_details_json["parameters"]["properties"].keys()) == {
        "email",
        "name",
        "notes",
    }
    assert record_unknown_question_json["name"] == "record_unknown_question"
    assert record_unknown_question_json["parameters"]["required"] == ["question"]


def test_tools_list_wraps_schemas_in_function_type():
    assert len(tools.tools) == 2
    for entry in tools.tools:
        assert entry["type"] == "function"
        assert "function" in entry
