"""The four panes, the table viewer and the status bar."""

from pystudio.widgets.console import ConsolePane
from pystudio.widgets.frame_viewer import FrameViewer
from pystudio.widgets.nvim_pane import NvimPane
from pystudio.widgets.plots import PROTOCOL, PlotsPane
from pystudio.widgets.status import StatusBar
from pystudio.widgets.variables import VariablesPane

__all__ = [
    "PROTOCOL",
    "ConsolePane",
    "FrameViewer",
    "NvimPane",
    "PlotsPane",
    "StatusBar",
    "VariablesPane",
]
