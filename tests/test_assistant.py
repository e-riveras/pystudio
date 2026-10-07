"""The assistant's loop and tools, against a scripted provider and a workspace of lists."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from pystudio.assistant import (
    Assistant,
    Notice,
    ProviderError,
    ProviderUnavailable,
    ToolNote,
    agent,
    load,
    tools,
)
from pystudio.assistant.anthropic_provider import (
    AnthropicProvider,
    echoable,
    tool_param,
    user_content,
)
from pystudio.assistant.provider import TextDelta, ToolCall, ToolResult, TurnEnd
from pystudio.introspect import Variable

from .conftest import HANG, Scripted


class Lists:
    """A workspace made of lists: a buffer, a cursor, and canned kernel answers."""

    def __init__(self, lines: list[str] | None = None, cursor: int = 1, cwd: Path | None = None):
        self.lines = list(lines) if lines is not None else [""]
        self.cursor = cursor
        self.cwd = cwd or Path.cwd()
        self.evaluated: list[str] = []
        self.edits = 0

    async def buffer(self) -> tuple[str, list[str], int]:
        return "analysis.py", list(self.lines), self.cursor

    async def cell_end(self) -> int:
        for index in range(self.cursor, len(self.lines)):
            if self.lines[index].startswith("# %%"):
                return index
        return len(self.lines)

    async def set_lines(self, start: int, end: int, lines: list[str]) -> None:
        self.lines[start:end] = lines
        self.edits += 1

    async def move_cursor(self, line: int) -> None:
        self.cursor = line

    async def variables(self) -> list[Variable]:
        return [Variable("df", "DataFrame", "(3, 2)", "a b")]

    async def evaluate(self, expression: str) -> tuple[bool, str]:
        self.evaluated.append(expression)
        if expression == "boom":
            return False, "NameError: name 'boom' is not defined"
        if expression == "slow":
            raise TimeoutError
        return True, "x" * 10_000 if expression == "wide" else "42"

    def console_tail(self, lines: int) -> str:
        return "Traceback\nZeroDivisionError"


def call(name: str, **arguments) -> ToolCall:
    return ToolCall(f"id-{name}", name, arguments)


async def result_of(workspace: Lists, name: str, **arguments) -> ToolResult:
    result, _ = await tools.run(workspace, call(name, **arguments))
    return result


CELLS = [
    {"title": "Load", "code": "df = pd.read_csv('a.csv')\n"},
    {"title": "Describe", "code": "df.describe()"},
]

# ---------------------------------------------------------------------------- tools


async def test_insert_cells_fills_an_empty_buffer() -> None:
    workspace = Lists()
    result = await result_of(workspace, "insert_cells", cells=CELLS)
    assert not result.is_error
    assert workspace.lines == [
        "# %% Load",
        "df = pd.read_csv('a.csv')",
        "",
        "# %% Describe",
        "df.describe()",
    ]
    assert workspace.cursor == 1
    assert workspace.edits == 1, "one edit is one undo step"


async def test_insert_cells_goes_after_the_cursors_cell() -> None:
    workspace = Lists(["# %% one", "a = 1", "# %% two", "b = 2"], cursor=2)
    await result_of(workspace, "insert_cells", cells=CELLS[:1])
    assert workspace.lines == [
        "# %% one",
        "a = 1",
        "",
        "# %% Load",
        "df = pd.read_csv('a.csv')",
        "",
        "# %% two",
        "b = 2",
    ]
    assert workspace.lines[workspace.cursor - 1] == "# %% Load"


async def test_insert_cells_at_the_end() -> None:
    workspace = Lists(["# %% one", "a = 1", "# %% two", "b = 2"], cursor=2)
    result = await result_of(workspace, "insert_cells", cells=CELLS[1:], where="end")
    assert workspace.lines[-3:] == ["", "# %% Describe", "df.describe()"]
    assert "lines 6-7" in result.text


async def test_replace_lines_rewrites_a_range() -> None:
    workspace = Lists(["a = 1", "b = 2", "c = 3"])
    await result_of(workspace, "replace_lines", start=2, end=3, code="b = 20\n")
    assert workspace.lines == ["a = 1", "b = 20"]


async def test_replace_lines_refuses_a_range_outside_the_buffer() -> None:
    workspace = Lists(["a = 1"])
    result = await result_of(workspace, "replace_lines", start=1, end=9, code="x")
    assert result.is_error
    assert workspace.lines == ["a = 1"]


async def test_read_buffer_numbers_the_lines() -> None:
    result = await result_of(Lists(["a = 1", "b = 2"], cursor=2), "read_buffer")
    assert "cursor: line 2" in result.text
    assert "1  a = 1\n2  b = 2" in result.text


async def test_inspect_returns_the_repr_and_cuts_a_long_one() -> None:
    workspace = Lists()
    assert (await result_of(workspace, "inspect", expression="1")).text == "42"
    wide = await result_of(workspace, "inspect", expression="wide")
    assert len(wide.text) < 5000
    assert "cut at" in wide.text


async def test_inspect_reports_what_the_expression_raised() -> None:
    result = await result_of(Lists(), "inspect", expression="boom")
    assert "NameError" in result.text


async def test_a_busy_kernel_is_an_error_result() -> None:
    result = await result_of(Lists(), "inspect", expression="slow")
    assert result.is_error
    assert "busy" in result.text


async def test_list_variables() -> None:
    result = await result_of(Lists(), "list_variables")
    assert "df\tDataFrame\t(3, 2)" in result.text


async def test_peek_file_reads_the_head_relative_to_the_workspace(tmp_path) -> None:
    (tmp_path / "a.csv").write_text("\n".join(f"row{n}" for n in range(1000)))
    workspace = Lists(cwd=tmp_path)
    result = await result_of(workspace, "peek_file", path="a.csv", lines=3)
    assert result.text.endswith("row0\nrow1\nrow2")
    capped = await result_of(workspace, "peek_file", path="a.csv", lines=100_000)
    assert capped.text.count("\n") == tools.PEEK_MAX_LINES


async def test_peek_file_refuses_binary_and_missing_files(tmp_path) -> None:
    (tmp_path / "a.bin").write_bytes(b"\0\1\2")
    workspace = Lists(cwd=tmp_path)
    assert (await result_of(workspace, "peek_file", path="a.bin")).is_error
    assert (await result_of(workspace, "peek_file", path="nope.csv")).is_error


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("insert_cells", {"cells": "not a list"}),
        ("insert_cells", {"cells": [{"title": "t"}]}),
        ("insert_cells", {"cells": CELLS, "where": "somewhere"}),
        ("replace_lines", {"start": "1", "end": 2, "code": ""}),
        ("inspect", {}),
        ("no_such_tool", {}),
    ],
)
async def test_bad_input_is_an_error_result_and_changes_nothing(name, arguments) -> None:
    workspace = Lists(["a = 1"])
    result = await result_of(workspace, name, **arguments)
    assert result.is_error
    assert workspace.lines == ["a = 1"]


# ----------------------------------------------------------------------------- loop


def assistant_with(provider: Scripted, workspace: Lists | None = None):
    shown: list = []
    return Assistant(provider, workspace or Lists(), shown.append), shown


async def test_tool_results_go_back_to_the_model() -> None:
    provider = Scripted(
        [call("inspect", expression="df.dtypes"), TurnEnd("tools")],
        [TextDelta("Added "), TextDelta("it."), TurnEnd("done")],
    )
    workspace = Lists()
    assistant, shown = assistant_with(provider, workspace)
    await assistant.ask("look at df")

    assert workspace.evaluated == ["df.dtypes"]
    assert provider.sent[0] == ("look at df", [])
    user, results = provider.sent[1]
    assert user is None
    assert results == [ToolResult("id-inspect", "42")]
    assert shown == [
        ToolNote("inspected `df.dtypes`"),
        TextDelta("Added "),
        TextDelta("it."),
        TurnEnd("done"),
    ]
    assert provider.tools == tools.SPECS


async def test_the_loop_stops_at_the_round_cap(monkeypatch) -> None:
    monkeypatch.setattr(agent, "MAX_ROUNDS", 3)
    provider = Scripted(*([call("list_variables"), TurnEnd("tools")] for _ in range(3)))
    assistant, shown = assistant_with(provider)
    await assistant.ask("loop")
    assert isinstance(shown[-1], Notice)
    assert provider.turns == []


async def test_a_refusal_ends_the_turn() -> None:
    assistant, shown = assistant_with(Scripted([TurnEnd("refused")]))
    await assistant.ask("no")
    assert shown == [TurnEnd("refused")]


async def test_a_provider_error_becomes_a_notice() -> None:
    assistant, shown = assistant_with(Scripted([ProviderError("rate limited")]))
    await assistant.ask("hi")
    assert shown == [Notice("rate limited")]


async def test_an_interrupted_turn_still_answers_its_tool_calls() -> None:
    """The model must get a result for every call, or the next request is rejected."""
    provider = Scripted(
        [call("inspect", expression="1"), call("list_variables"), TurnEnd("tools")],
        [HANG],
        [TurnEnd("done")],
    )
    assistant, _ = assistant_with(provider)
    task = asyncio.create_task(assistant.ask("first"))
    while len(provider.sent) < 1 or len(provider.turns) > 1:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await assistant.ask("second")
    user, results = provider.sent[-1]
    assert user == "second"
    assert [result.id for result in results] == ["id-inspect", "id-list_variables"]


# ------------------------------------------------------------------------ providers


def test_an_unknown_provider_is_unavailable() -> None:
    with pytest.raises(ProviderUnavailable, match="known: anthropic"):
        load("nope")


def test_tools_are_declared_in_the_api_shape() -> None:
    declared = tool_param(tools.SPECS[1])
    assert declared["name"] == "insert_cells"
    assert declared["eager_input_streaming"] is True
    assert declared["input_schema"]["additionalProperties"] is False


def test_tool_results_come_before_the_users_text() -> None:
    content = user_content("next", [ToolResult("t1", "ok"), ToolResult("t2", "bad", True)])
    assert [block["type"] for block in content] == ["tool_result", "tool_result", "text"]
    assert content[1] == {
        "type": "tool_result",
        "tool_use_id": "t2",
        "content": "bad",
        "is_error": True,
    }


def block(kind: str, **fields) -> SimpleNamespace:
    return SimpleNamespace(type=kind, **fields)


def test_a_reply_is_echoed_whole_unless_it_fell_back() -> None:
    plain = [block("thinking"), block("text"), block("tool_use")]
    assert echoable(plain) == plain
    switched = [
        block("thinking"),
        block("text"),
        block("tool_use"),
        block("fallback"),
        block("thinking"),
        block("tool_use"),
    ]
    assert [b.type for b in echoable(switched)] == ["text", "fallback", "thinking", "tool_use"]


class FakeStream:
    def __init__(self, reply: SimpleNamespace, texts: list[str]) -> None:
        self.reply, self.texts = reply, texts

    async def __aenter__(self) -> FakeStream:
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def __aiter__(self):
        for text in self.texts:
            yield SimpleNamespace(type="text", text=text)

    async def get_final_message(self) -> SimpleNamespace:
        return self.reply


class FakeClient:
    """Stands in for ``AsyncAnthropic``: replays replies, records each request."""

    def __init__(self, *replies: SimpleNamespace) -> None:
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    def stream(self, **request) -> FakeStream:
        self.requests.append({**request, "messages": list(request["messages"])})
        reply = self.replies.pop(0)
        texts = [b.text for b in reply.content if b.type == "text"]
        return FakeStream(reply, texts)


def reply(stop_reason: str, *content: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop_reason, content=list(content))


async def events(conversation, **kwargs) -> list:
    return [event async for event in conversation.send(**kwargs)]


async def test_anthropic_turns_a_reply_into_events_and_keeps_the_transcript() -> None:
    use = block("tool_use", id="t1", name="inspect", input={"expression": "df"})
    client = FakeClient(
        reply("tool_use", block("thinking"), block("text", text="Looking."), use),
        reply("end_turn", block("text", text="Done.")),
    )
    conversation = AnthropicProvider(client=client).start("system", tools.SPECS)

    first = await events(conversation, user="eda please")
    assert first == [
        TextDelta("Looking."),
        ToolCall("t1", "inspect", {"expression": "df"}),
        TurnEnd("tools"),
    ]
    second = await events(conversation, results=[ToolResult("t1", "42")])
    assert second == [TextDelta("Done."), TurnEnd("done")]

    request = client.requests[1]
    assert request["model"] == "claude-sonnet-5-5"
    assert request["fallbacks"] == "default"
    assert [message["role"] for message in request["messages"]] == ["user", "assistant", "user"]
    # The assistant turn goes back whole, thinking block included.
    assert [b.type for b in request["messages"][1]["content"]] == ["thinking", "text", "tool_use"]
    assert request["messages"][2]["content"][0]["tool_use_id"] == "t1"


async def test_anthropic_drops_a_refused_or_cut_off_turn() -> None:
    cut = block("tool_use", id="t1", name="insert_cells", input={"cells": []})
    client = FakeClient(reply("refusal"), reply("max_tokens", cut))
    conversation = AnthropicProvider(client=client).start("system", tools.SPECS)

    assert await events(conversation, user="a") == [TurnEnd("refused")]
    assert await events(conversation, user="b") == [TurnEnd("truncated")]
    assert conversation.messages == []


async def test_anthropic_model_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("PYSTUDIO_ASSISTANT_MODEL", "claude-opus-5-5")
    assert AnthropicProvider().model == "claude-opus-5-5"
