"""Claude, through the Anthropic SDK. The only module that imports it.

Credentials are whatever the SDK finds: ``ANTHROPIC_API_KEY``,
``ANTHROPIC_AUTH_TOKEN``, or a profile from ``ant auth login``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Sequence
from typing import Any

import anthropic

from pystudio.assistant.provider import (
    Event,
    ProviderError,
    ProviderUnavailable,
    TextDelta,
    ToolCall,
    ToolResult,
    ToolSpec,
    TurnEnd,
)

DEFAULT_MODEL = "claude-sonnet-5-5"
MODEL_VARIABLE = "PYSTUDIO_ASSISTANT_MODEL"
MAX_TOKENS = 64_000
FALLBACK_BETA = "server-side-fallback-2026-07-01"
"""Lets the API retry a request the model declines on another model, server-side."""
JSON_RETRIES = 2
NO_CREDENTIALS = (
    "The assistant needs Anthropic credentials: set ANTHROPIC_API_KEY, or run `ant auth login`."
)
INTERNAL_BLOCKS = ("thinking", "redacted_thinking", "tool_use")


def tool_param(spec: ToolSpec) -> dict[str, Any]:
    """A tool in the API's shape. Its input streams as written rather than
    arriving in one burst, which leaves validating it to :mod:`pystudio.assistant.tools`."""
    return {
        "name": spec.name,
        "description": spec.description,
        "input_schema": spec.schema,
        "eager_input_streaming": True,
    }


def user_content(user: str | None, results: Sequence[ToolResult]) -> list[dict[str, Any]]:
    """One user turn: every tool result first, then what the user typed."""
    content: list[dict[str, Any]] = [
        {
            "type": "tool_result",
            "tool_use_id": result.id,
            "content": result.text,
            "is_error": result.is_error,
        }
        for result in results
    ]
    if user:
        content.append({"type": "text", "text": user})
    return content


def echoable(content: Sequence[Any]) -> list[Any]:
    """The blocks of a reply that go back to the API on the next request.

    Normally all of them, unchanged. When the request fell back to another
    model mid-reply, the first model's thinking and tool calls from before the
    switch must be left out.
    """
    blocks = list(content)
    switches = [index for index, block in enumerate(blocks) if block.type == "fallback"]
    if not switches:
        return blocks
    return [
        block
        for index, block in enumerate(blocks)
        if index > switches[-1] or block.type not in INTERNAL_BLOCKS
    ]


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self, *, model: str | None = None, client: anthropic.AsyncAnthropic | None = None
    ) -> None:
        self.model = model or os.environ.get(MODEL_VARIABLE) or DEFAULT_MODEL
        self._client = client

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic()
        return self._client

    def start(self, system: str, tools: Sequence[ToolSpec]) -> AnthropicConversation:
        return AnthropicConversation(self, system, [tool_param(spec) for spec in tools])


class AnthropicConversation:
    """The message list in the API's own shape, grown one committed turn at a time."""

    def __init__(
        self, provider: AnthropicProvider, system: str, tools: list[dict[str, Any]]
    ) -> None:
        self.provider = provider
        self.system = system
        self.tools = tools
        self.messages: list[dict[str, Any]] = []

    async def send(
        self, *, user: str | None = None, results: Sequence[ToolResult] = ()
    ) -> AsyncIterator[Event]:
        # Built on a copy, and committed only once the reply is whole, so a
        # failed or cancelled request leaves the transcript as it was.
        messages = [*self.messages, {"role": "user", "content": user_content(user, results)}]
        bad_json = 0
        while True:
            try:
                async with self.provider.client.beta.messages.stream(
                    model=self.provider.model,
                    max_tokens=MAX_TOKENS,
                    system=self.system,
                    tools=self.tools,
                    messages=messages,
                    thinking={"type": "adaptive"},
                    output_config={"effort": "high"},
                    cache_control={"type": "ephemeral"},
                    betas=[FALLBACK_BETA],
                    fallbacks="default",
                ) as stream:
                    async for event in stream:
                        if event.type == "text":
                            yield TextDelta(event.text)
                    reply = await stream.get_final_message()
            except ValueError as error:
                # Tool input the SDK could not parse at all. There is no call
                # to answer yet, so the request is simply made again.
                bad_json += 1
                if bad_json > JSON_RETRIES:
                    raise ProviderError("the model kept sending unreadable tool input") from error
                continue
            except anthropic.AuthenticationError as error:
                raise ProviderUnavailable(
                    f"Anthropic rejected the credentials. {NO_CREDENTIALS}"
                ) from error
            except anthropic.RateLimitError as error:
                raise ProviderError("rate limited by Anthropic; try again shortly") from error
            except anthropic.APIStatusError as error:
                raise ProviderError(
                    f"Anthropic API error {error.status_code}: {error.message}"
                ) from error
            except anthropic.APIConnectionError as error:
                raise ProviderError("could not reach the Anthropic API") from error
            except anthropic.AnthropicError as error:
                raise ProviderError(f"Anthropic SDK error: {error}") from error
            except TypeError as error:
                # How the SDK reports that it found no credentials at all.
                if "authentication" not in str(error):
                    raise
                raise ProviderUnavailable(NO_CREDENTIALS) from error

            if reply.stop_reason == "refusal":
                # Nothing of a declined turn is kept, the question included.
                yield TurnEnd("refused")
                return
            content = echoable(reply.content)
            messages.append({"role": "assistant", "content": content})
            if reply.stop_reason == "pause_turn":
                continue
            break

        calls = [block for block in content if block.type == "tool_use"]
        if reply.stop_reason == "max_tokens":
            # A tool call cut off mid-input parses as a valid partial one, so
            # the turn is dropped rather than run or left waiting on results.
            if not calls:
                self.messages = messages
            yield TurnEnd("truncated")
            return
        self.messages = messages
        for block in calls:
            # Not validated by the API; the tools check their own input.
            arguments = block.input if isinstance(block.input, dict) else {}
            yield ToolCall(block.id, block.name, arguments)
        yield TurnEnd("tools" if calls else "done")
