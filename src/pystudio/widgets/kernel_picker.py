"""A list of kernels to switch to: the project's, the registered, the running."""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from pystudio.interpreter import KernelChoice


class KernelPicker(ModalScreen[KernelChoice | None]):
    """Modal list over the kernel choices. Enter picks one, escape closes it."""

    BINDINGS = [Binding("escape,q", "dismiss(None)", "close")]

    DEFAULT_CSS = """
    KernelPicker {
        align: center middle;
        background: $background 60%;
    }
    KernelPicker > #picker-box {
        width: 70%;
        height: auto;
        max-height: 80%;
        border: round $accent;
        border-title-color: $accent;
        border-title-align: left;
        background: $surface;
    }
    KernelPicker #picker-list {
        height: auto;
        max-height: 100%;
        border: none;
        background: transparent;
    }
    KernelPicker #picker-caption {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(self, choices: list[KernelChoice], current: KernelChoice) -> None:
        super().__init__()
        self.choices = choices
        self.current = current

    def compose(self):
        with Vertical(id="picker-box"):
            yield OptionList(*(self._option(choice) for choice in self.choices), id="picker-list")
            yield Static("enter switches · escape closes", id="picker-caption")

    def on_mount(self) -> None:
        self.query_one("#picker-box").border_title = "kernels"
        for position, choice in enumerate(self.choices):
            if choice.target == self.current.target:
                self.query_one(OptionList).highlighted = position
                break

    def _option(self, choice: KernelChoice) -> Option:
        line = Text("● " if choice.target == self.current.target else "  ")
        line.append(choice.label)
        line.append(f"  {choice.detail}", style="dim")
        return Option(line)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.choices[event.option_index])
