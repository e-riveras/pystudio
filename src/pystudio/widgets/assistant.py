"""The assistant's chat: what was asked, what it did, and a prompt to ask more."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Input, Static

from pystudio.widgets.console import Prompt

GREETING = (
    "Ask for code in plain words, such as: do some EDA on data/sales.csv. "
    "Cells are written into the editor; you run them. escape cancels a reply."
)


class AssistantPane(Vertical):
    """Messages above, prompt below. The reply being written grows in place."""

    DEFAULT_CSS = """
    AssistantPane {
        layout: vertical;
    }
    AssistantPane > VerticalScroll {
        height: 1fr;
        background: transparent;
    }
    AssistantPane .message {
        height: auto;
        padding: 0 0 1 0;
    }
    AssistantPane > Input {
        height: 1;
        border: none;
        padding: 0;
        background: transparent;
    }
    """

    @dataclass
    class Asked(Message):
        """The user sent a request."""

        text: str

    class Cancelled(Message):
        """The user pressed escape at the prompt."""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.entries: list[Text] = []
        self._reply: Static | None = None

    def compose(self):
        yield VerticalScroll(id="assistant-log", can_focus=False)
        yield Prompt(id="assistant-prompt", placeholder="ask the assistant", compact=True)

    def on_mount(self) -> None:
        self.show_note(GREETING)

    @property
    def log_widget(self) -> VerticalScroll:
        return self.query_one("#assistant-log", VerticalScroll)

    @property
    def prompt(self) -> Input:
        return self.query_one("#assistant-prompt", Input)

    @property
    def transcript(self) -> str:
        """Everything in the chat, as plain text."""
        return "\n".join(entry.plain for entry in self.entries)

    # --------------------------------------------------------------------- writing

    def _add(self, text: Text) -> Static:
        self.entries.append(text)
        message = Static(text, classes="message")
        log = self.log_widget
        log.mount(message)
        log.scroll_end(animate=False)
        return message

    def show_user(self, text: str) -> None:
        self.end_reply()
        self._add(Text.assemble(("you  ", "bold cyan"), text))

    def show_note(self, text: str) -> None:
        """A dim line that is not the model speaking: a tool at work, a notice."""
        self.end_reply()
        self._add(Text(text, style="dim italic"))

    def stream(self, text: str) -> None:
        """Append to the reply being written, starting one if there is none."""
        if self._reply is None:
            self._reply = self._add(Text())
        entry = self.entries[-1]
        entry.append(text)
        self._reply.update(entry)
        self.log_widget.scroll_end(animate=False)

    def end_reply(self) -> None:
        self._reply = None

    # ----------------------------------------------------------------------- input

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        text = event.value.strip()
        self.prompt.value = ""
        if text:
            self.post_message(self.Asked(text))

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            self.post_message(self.Cancelled())
