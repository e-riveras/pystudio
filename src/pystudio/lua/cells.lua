-- Cell decoration: a rule above every `# %%` marker, and a faint wash over the
-- cell the cursor is in, so what `send_cell` will send is visible.
--
-- Two namespaces, because the rules only change when the text does, while the
-- current-cell wash follows the cursor.

local pystudio = _G.pystudio

local rules_ns = vim.api.nvim_create_namespace("pystudio_cell_rules")
local current_ns = vim.api.nvim_create_namespace("pystudio_cell_current")

vim.api.nvim_set_hl(0, "PyStudioCellBorder", { link = "Comment", default = true })
vim.api.nvim_set_hl(0, "PyStudioCell", { link = "CursorLine", default = true })

local state = { first = 0, last = 0, width = 0 }

local function decorated()
  return vim.bo.filetype == "python"
end

local function draw_rules()
  local buf = vim.api.nvim_get_current_buf()
  vim.api.nvim_buf_clear_namespace(buf, rules_ns, 0, -1)
  if not decorated() then
    return
  end
  local width = vim.api.nvim_win_get_width(0)
  state.width = width
  local rule = string.rep("\u{2500}", math.max(width - 1, 1))
  local lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
  for i, line in ipairs(lines) do
    -- Nothing to separate above the first line.
    if i > 1 and pystudio.is_marker(line) then
      vim.api.nvim_buf_set_extmark(buf, rules_ns, i - 1, 0, {
        virt_lines = { { { rule, "PyStudioCellBorder" } } },
        virt_lines_above = true,
      })
    end
  end
end

local function draw_current(force)
  local buf = vim.api.nvim_get_current_buf()
  if not decorated() then
    vim.api.nvim_buf_clear_namespace(buf, current_ns, 0, -1)
    return
  end
  local first, last = pystudio.cell_range()
  if not force and first == state.first and last == state.last then
    return
  end
  state.first, state.last = first, last
  vim.api.nvim_buf_clear_namespace(buf, current_ns, 0, -1)
  for i = first, last do
    vim.api.nvim_buf_set_extmark(buf, current_ns, i - 1, 0, {
      line_hl_group = "PyStudioCell",
    })
  end
end

local function redraw()
  draw_rules()
  draw_current(true)
end

vim.api.nvim_create_augroup("pystudio_cells", { clear = true })
vim.api.nvim_create_autocmd({
  "BufEnter",
  "BufWritePost",
  "TextChanged",
  "InsertLeave",
  "FileType",
}, {
  group = "pystudio_cells",
  callback = redraw,
})
vim.api.nvim_create_autocmd({ "WinResized", "VimResized" }, {
  group = "pystudio_cells",
  callback = function()
    if vim.api.nvim_win_get_width(0) ~= state.width then
      redraw()
    end
  end,
})
vim.api.nvim_create_autocmd({ "CursorMoved", "CursorMovedI" }, {
  group = "pystudio_cells",
  callback = function()
    draw_current(false)
  end,
})

_G.pystudio_cells = {
  redraw = redraw,
  rules_ns = rules_ns,
  current_ns = current_ns,
}

redraw()
return true
