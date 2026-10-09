"""pystudio: a terminal IDE for Python data science, with Neovim as its editor.

The pieces are deliberately separable:

``pystudio.kernel``
    One Jupyter kernel and the tasks that pump its channels. No UI.
``pystudio.nvim``
    msgpack-RPC to ``nvim --embed``, the screen model it paints into, and key
    translation. No UI.
``pystudio.widgets`` and ``pystudio.app``
    The Textual shell that puts those two together in four panes.
"""

__version__ = "0.2.1"
