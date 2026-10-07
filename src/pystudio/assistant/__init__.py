"""The assistant: a chat that writes cells into the editor.

Nothing in this package imports a widget. A provider turns a conversation into
text and tool calls, the tools act on a :class:`~pystudio.assistant.tools.Workspace`,
and the app supplies both.
"""

from pystudio.assistant.agent import Assistant, Notice, ToolNote
from pystudio.assistant.provider import (
    Provider,
    ProviderError,
    ProviderUnavailable,
    TextDelta,
    TurnEnd,
    load,
)

__all__ = [
    "Assistant",
    "Notice",
    "Provider",
    "ProviderError",
    "ProviderUnavailable",
    "TextDelta",
    "ToolNote",
    "TurnEnd",
    "load",
]
