"""The seam between the assistant and whichever model answers it.

A provider owns its transcript in its own wire format, because that format is
not neutral: Anthropic, for one, wants its thinking blocks echoed back
unchanged. So the assistant never sees messages, only what it must act on: text
to show, tools to run, and why the turn ended.
"""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


class ProviderError(Exception):
    """The provider could not answer. The message is fit to show the user."""


class ProviderUnavailable(ProviderError):
    """The provider cannot be used at all: unknown, not installed, or no credentials."""


@dataclass(frozen=True)
class ToolSpec:
    """A tool the model may call, described by a JSON schema for its input."""

    name: str
    description: str
    schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """The model asked for a tool to be run."""

    id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """What a tool answered, to be sent back with the next turn."""

    id: str
    text: str
    is_error: bool = False


@dataclass(frozen=True)
class TextDelta:
    """A piece of the reply, as it is written."""

    text: str


@dataclass(frozen=True)
class TurnEnd:
    """Why the model stopped: finished, waiting on tools, declined, or cut off."""

    reason: Literal["done", "tools", "refused", "truncated"]


Event = TextDelta | ToolCall | TurnEnd


class Conversation(Protocol):
    """One chat. Each ``send`` is a request, streamed back as events."""

    def send(
        self, *, user: str | None = None, results: Sequence[ToolResult] = ()
    ) -> AsyncIterator[Event]:
        """Send the user's text, the results of the last tool calls, or both.

        Ends with exactly one :class:`TurnEnd`. Raises :class:`ProviderError`.
        A turn that fails or is cancelled must leave the transcript as it was.
        """
        ...


class Provider(Protocol):
    name: str

    def start(self, system: str, tools: Sequence[ToolSpec]) -> Conversation: ...


PROVIDERS = {"anthropic": "pystudio.assistant.anthropic_provider:AnthropicProvider"}
"""Provider name to ``module:class``, imported only when asked for."""


def load(name: str) -> Provider:
    """Build the named provider. Raises :class:`ProviderUnavailable`."""
    target = PROVIDERS.get(name)
    if target is None:
        known = ", ".join(sorted(PROVIDERS))
        raise ProviderUnavailable(f"unknown assistant provider {name!r}; known: {known}")
    module_name, _, class_name = target.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise ProviderUnavailable(f"the {name} provider is not installed: {error}") from error
    provider: Provider = getattr(module, class_name)()
    return provider
