from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import me_agent
from me_agent import Me


def _make_me() -> Me:
    """Build a Me instance without running __init__ (avoids disk reads)."""
    me = Me.__new__(Me)
    me.client = MagicMock()
    me.client.chat = MagicMock()
    me.client.chat.completions = MagicMock()
    me.client.chat.completions.create = AsyncMock()
    me.name = "TestPerson"
    me.model = "gpt-test"
    me.max_tokens = 100
    me.linkedin = "LINKEDIN_DATA"
    me.summary = "SUMMARY_DATA"
    return me


def _tool_call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _response(
    content: str | None = "hello",
    finish_reason: str = "stop",
    tool_calls: list | None = None,
    total_tokens: int | None = 42,
) -> SimpleNamespace:
    usage = SimpleNamespace(total_tokens=total_tokens) if total_tokens is not None else None
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(finish_reason=finish_reason, message=message)
    return SimpleNamespace(usage=usage, choices=[choice])


# ---------- system_prompt ----------


def test_system_prompt_includes_name_summary_and_linkedin():
    me = _make_me()
    prompt = me.system_prompt()
    assert "TestPerson" in prompt
    assert "SUMMARY_DATA" in prompt
    assert "LINKEDIN_DATA" in prompt


# ---------- _handle_tool_calls ----------


def test_handle_tool_calls_dispatches_known_tool(monkeypatch):
    fake = MagicMock(return_value={"recorded": "ok"})
    monkeypatch.setitem(me_agent.TOOL_REGISTRY, "record_user_details", fake)

    me = _make_me()
    call = _tool_call("call_1", "record_user_details", '{"email":"x@y.com"}')
    results = me._handle_tool_calls([call])

    fake.assert_called_once_with(email="x@y.com")
    assert results == [
        {"role": "tool", "content": '{"recorded": "ok"}', "tool_call_id": "call_1"}
    ]


def test_handle_tool_calls_returns_error_for_unknown_tool():
    me = _make_me()
    call = _tool_call("call_2", "no_such_tool", "{}")
    results = me._handle_tool_calls([call])
    assert len(results) == 1
    assert results[0]["tool_call_id"] == "call_2"
    assert '"error"' in results[0]["content"]
    assert "unknown_tool" in results[0]["content"]


def test_handle_tool_calls_recovers_from_invalid_json_arguments(monkeypatch):
    fake = MagicMock(return_value={"recorded": "ok"})
    monkeypatch.setitem(me_agent.TOOL_REGISTRY, "record_unknown_question", fake)

    me = _make_me()
    call = _tool_call("call_3", "record_unknown_question", "{not json")
    me._handle_tool_calls([call])

    fake.assert_called_once_with()  # empty kwargs after JSON failure


def test_handle_tool_calls_recovers_from_empty_arguments(monkeypatch):
    fake = MagicMock(return_value={"recorded": "ok"})
    monkeypatch.setitem(me_agent.TOOL_REGISTRY, "record_unknown_question", fake)

    me = _make_me()
    call = _tool_call("call_4", "record_unknown_question", "")
    me._handle_tool_calls([call])

    fake.assert_called_once_with()


def test_handle_tool_calls_processes_multiple_calls_in_order(monkeypatch):
    fake = MagicMock(return_value={"recorded": "ok"})
    monkeypatch.setitem(me_agent.TOOL_REGISTRY, "record_unknown_question", fake)

    me = _make_me()
    calls = [
        _tool_call("a", "record_unknown_question", '{"question":"q1"}'),
        _tool_call("b", "record_unknown_question", '{"question":"q2"}'),
    ]
    results = me._handle_tool_calls(calls)
    assert [r["tool_call_id"] for r in results] == ["a", "b"]
    assert fake.call_count == 2


# ---------- chat_async ----------


async def test_chat_async_returns_content_tokens_and_model_on_happy_path():
    me = _make_me()
    me.client.chat.completions.create.return_value = _response(
        content="hi there", finish_reason="stop", total_tokens=42
    )

    reply, tokens, model = await me.chat_async("hello", history=[])

    assert reply == "hi there"
    assert tokens == 42
    assert model == "gpt-test"
    me.client.chat.completions.create.assert_awaited_once()


async def test_chat_async_passes_system_history_and_user_message():
    me = _make_me()
    me.client.chat.completions.create.return_value = _response()

    history = [
        {"role": "user", "content": "earlier-q"},
        {"role": "assistant", "content": "earlier-a"},
    ]
    await me.chat_async("new question", history=history)

    kwargs = me.client.chat.completions.create.await_args.kwargs
    msgs = kwargs["messages"]
    assert msgs[0]["role"] == "system"
    assert "TestPerson" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "earlier-q"}
    assert msgs[2] == {"role": "assistant", "content": "earlier-a"}
    assert msgs[3] == {"role": "user", "content": "new question"}
    assert kwargs["model"] == "gpt-test"
    assert kwargs["max_tokens"] == 100
    assert kwargs["tool_choice"] == "auto"


async def test_chat_async_returns_empty_string_when_content_is_none():
    me = _make_me()
    me.client.chat.completions.create.return_value = _response(content=None)
    reply, _, _ = await me.chat_async("hi", history=[])
    assert reply == ""


async def test_chat_async_runs_tool_loop_then_returns_final_content(monkeypatch):
    fake_tool = MagicMock(return_value={"recorded": "ok"})
    monkeypatch.setitem(me_agent.TOOL_REGISTRY, "record_user_details", fake_tool)

    me = _make_me()
    tool_call = _tool_call("c1", "record_user_details", '{"email":"a@b.c"}')
    first = _response(
        content=None,
        finish_reason="tool_calls",
        tool_calls=[tool_call],
        total_tokens=10,
    )
    second = _response(content="thanks, recorded", finish_reason="stop", total_tokens=15)
    me.client.chat.completions.create.side_effect = [first, second]

    reply, tokens, model = await me.chat_async("here's my email", history=[])

    assert reply == "thanks, recorded"
    assert tokens == 25  # accumulated across both calls
    assert model == "gpt-test"
    fake_tool.assert_called_once_with(email="a@b.c")
    assert me.client.chat.completions.create.await_count == 2


async def test_chat_async_bounded_loop_returns_empty_after_five_tool_rounds(monkeypatch):
    fake_tool = MagicMock(return_value={"recorded": "ok"})
    monkeypatch.setitem(me_agent.TOOL_REGISTRY, "record_unknown_question", fake_tool)

    me = _make_me()
    looping = _response(
        content=None,
        finish_reason="tool_calls",
        tool_calls=[_tool_call("x", "record_unknown_question", '{"question":"q"}')],
        total_tokens=5,
    )
    me.client.chat.completions.create.return_value = looping

    reply, tokens, model = await me.chat_async("hi", history=[])

    assert reply == ""
    assert tokens == 25  # 5 iterations * 5 tokens
    assert model == "gpt-test"
    assert me.client.chat.completions.create.await_count == 5


async def test_chat_async_handles_response_without_usage():
    me = _make_me()
    me.client.chat.completions.create.return_value = _response(
        content="ok", total_tokens=None
    )
    reply, tokens, _ = await me.chat_async("hi", history=[])
    assert reply == "ok"
    assert tokens == 0


async def test_chat_async_finish_reason_tool_calls_but_no_calls_returns_content():
    """Defensive: if finish_reason says tool_calls but list is empty/None, fall through."""
    me = _make_me()
    me.client.chat.completions.create.return_value = _response(
        content="fallback content", finish_reason="tool_calls", tool_calls=None
    )
    reply, _, _ = await me.chat_async("hi", history=[])
    assert reply == "fallback content"
