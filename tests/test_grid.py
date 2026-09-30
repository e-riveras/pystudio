"""The redraw protocol, fed synthetic event batches."""

from __future__ import annotations

from pystudio.nvim.grid import Grid


def redraw(*events: list) -> list:
    return list(events)


def test_resize_allocates_and_keeps_overlap() -> None:
    grid = Grid(4, 2)
    grid.handle_redraw(redraw(["grid_line", [1, 0, 0, [["a"], ["b"]]]]))
    grid.handle_redraw(redraw(["grid_resize", [1, 6, 3]]))
    assert (grid.width, grid.height) == (6, 3)
    assert grid.row_text(0) == "ab    "


def test_grid_line_reuses_highlight_and_repeats() -> None:
    grid = Grid(8, 1)
    grid.handle_redraw(
        redraw(["grid_line", [1, 0, 0, [["x", 7], ["y"], ["-", 9, 3], ["z", 0]]]]),
    )
    assert grid.row_text(0) == "xy---z  "
    # The second cell carries no id, so it inherits the first cell's.
    assert grid.hl[0][:6] == [7, 7, 9, 9, 9, 0]


def test_flush_is_reported() -> None:
    grid = Grid(2, 1)
    assert grid.handle_redraw(redraw(["grid_line", [1, 0, 0, [["a"]]]])) is False
    assert grid.handle_redraw(redraw(["flush", []])) is True


def test_scroll_up_moves_rows_toward_the_top() -> None:
    grid = Grid(3, 4)
    for row, text in enumerate("abcd"):
        grid.handle_redraw(redraw(["grid_line", [1, row, 0, [[text, 0, 3]]]]))
    grid.handle_redraw(redraw(["grid_scroll", [1, 0, 4, 0, 3, 1, 0]]))
    assert [grid.row_text(y) for y in range(4)] == ["bbb", "ccc", "ddd", "ddd"]


def test_scroll_down_moves_rows_toward_the_bottom() -> None:
    grid = Grid(3, 4)
    for row, text in enumerate("abcd"):
        grid.handle_redraw(redraw(["grid_line", [1, row, 0, [[text, 0, 3]]]]))
    grid.handle_redraw(redraw(["grid_scroll", [1, 0, 4, 0, 3, -1, 0]]))
    assert [grid.row_text(y) for y in range(4)] == ["aaa", "aaa", "bbb", "ccc"]


def test_scroll_respects_the_column_span() -> None:
    grid = Grid(4, 2)
    grid.handle_redraw(redraw(["grid_line", [1, 0, 0, [["1"], ["2"], ["3"], ["4"]]]]))
    grid.handle_redraw(redraw(["grid_line", [1, 1, 0, [["a"], ["b"], ["c"], ["d"]]]]))
    grid.handle_redraw(redraw(["grid_scroll", [1, 0, 2, 1, 3, 1, 0]]))
    assert grid.row_text(0) == "1bc4"


def test_double_width_cell_is_not_padded() -> None:
    grid = Grid(4, 1)
    # Neovim sends the wide character, then an empty cell for its second half.
    grid.handle_redraw(redraw(["grid_line", [1, 0, 0, [["世"], [""], ["!"]]]]))
    assert "".join(segment.text for segment in grid.row_segments(0)) == "世! "


def test_styles_use_the_declared_colors() -> None:
    grid = Grid(2, 1)
    grid.handle_redraw(
        redraw(
            ["default_colors_set", [0xFFFFFF, 0x000000, 0xFF0000, 0, 0]],
            ["hl_attr_define", [1, {"foreground": 0x00FF00, "bold": True}, {}, []]],
        )
    )
    style = grid.style_for(1)
    assert style.color is not None and style.color.triplet.hex == "#00ff00"
    assert style.bgcolor is not None and style.bgcolor.triplet.hex == "#000000"
    assert style.bold is True


def test_reverse_resolves_against_the_defaults() -> None:
    grid = Grid(2, 1)
    grid.handle_redraw(
        redraw(
            ["default_colors_set", [0xAABBCC, 0x112233, 0xFF0000, 0, 0]],
            ["hl_attr_define", [2, {"reverse": True}, {}, []]],
        )
    )
    style = grid.style_for(2)
    assert style.color is not None and style.color.triplet.hex == "#112233"
    assert style.bgcolor is not None and style.bgcolor.triplet.hex == "#aabbcc"


def test_changing_defaults_invalidates_cached_styles() -> None:
    grid = Grid(2, 1)
    grid.handle_redraw(redraw(["hl_attr_define", [3, {"bold": True}, {}, []]]))
    first = grid.style_for(3)
    grid.handle_redraw(redraw(["default_colors_set", [0x101010, 0x202020, 0, 0, 0]]))
    second = grid.style_for(3)
    assert first != second
    assert second.bgcolor is not None and second.bgcolor.triplet.hex == "#202020"


def test_underline_variants_collapse() -> None:
    grid = Grid(2, 1)
    grid.handle_redraw(
        redraw(
            ["hl_attr_define", [4, {"undercurl": True}, {}, []]],
            ["hl_attr_define", [5, {"underdouble": True}, {}, []]],
        )
    )
    assert grid.style_for(4).underline is True
    assert grid.style_for(5).underline2 is True


def test_cursor_cell_is_reversed() -> None:
    grid = Grid(3, 1)
    grid.handle_redraw(redraw(["grid_line", [1, 0, 0, [["a"], ["b"], ["c"]]]]))
    segments = grid.row_segments(0, cursor=1)
    assert [segment.text for segment in segments] == ["a", "b", "c"]
    assert segments[1].style is not None and segments[1].style.reverse is True


def test_mode_drives_the_cursor_shape() -> None:
    grid = Grid(2, 1)
    grid.handle_redraw(
        redraw(
            [
                "mode_info_set",
                [True, [{"cursor_shape": "block"}, {"cursor_shape": "vertical"}]],
            ],
            ["mode_change", ["insert", 1]],
        )
    )
    assert grid.mode == "insert"
    assert grid.cursor_shape == "vertical"


def test_unknown_events_are_ignored() -> None:
    grid = Grid(2, 1)
    grid.handle_redraw(redraw(["win_viewport", [1, 1000, 0, 5, 0, 20, 0, 1]], ["mouse_on", []]))
    assert grid.mouse_enabled is True
