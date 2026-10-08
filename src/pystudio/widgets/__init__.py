"""The panes, the table viewer, the kernel picker and the status bar."""

from pystudio.widgets.assistant import AssistantPane
from pystudio.widgets.console import ConsolePane
from pystudio.widgets.frame_viewer import FrameViewer
from pystudio.widgets.kernel_picker import KernelPicker
from pystudio.widgets.layout import Panes
from pystudio.widgets.nvim_pane import NvimPane
from pystudio.widgets.plot_gallery import PlotGallery
from pystudio.widgets.plots import PROTOCOL, PlotsPane
from pystudio.widgets.status import StatusBar
from pystudio.widgets.variables import VariablesPane

__all__ = [
    "PROTOCOL",
    "AssistantPane",
    "ConsolePane",
    "FrameViewer",
    "KernelPicker",
    "NvimPane",
    "Panes",
    "PlotGallery",
    "PlotsPane",
    "StatusBar",
    "VariablesPane",
]
