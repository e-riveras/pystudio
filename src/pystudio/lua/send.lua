-- Installed into the embedded Neovim once the UI is attached.
--
-- pystudio calls nvim_exec_lua with this source and its own RPC channel, so the
-- keymaps below can notify the IDE directly. Nothing is written to disk and no
-- terminal is involved: the lines travel over the same channel that carries the
-- redraw events back.

local chan = ...

local M = {}

-- Cell markers, matching the convention Spyder, VS Code and molten-nvim use.
local MARKERS = { "^%s*#%s*%%%%", "^%s*#%s*In%[" }

function M.is_marker(line)
  if line == nil then
    return false
  end
  for _, pattern in ipairs(MARKERS) do
    if line:match(pattern) then
      return true
    end
  end
  return false
end

local function in_visual_mode()
  local mode = vim.fn.mode()
  return mode == "v" or mode == "V" or mode == "\22"
end

local function goto_line(line)
  local total = vim.api.nvim_buf_line_count(0)
  vim.api.nvim_win_set_cursor(0, { math.max(1, math.min(line, total)), 0 })
end

--- The inclusive line range of the cell holding the cursor, markers excluded.
--- Returns first, last and the buffer's lines.
function M.cell_range()
  local lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
  local cursor = vim.api.nvim_win_get_cursor(0)[1]

  local first = 1
  for i = cursor, 1, -1 do
    if M.is_marker(lines[i]) then
      first = i + 1
      break
    end
  end

  local last = #lines
  for i = cursor + 1, #lines do
    if M.is_marker(lines[i]) then
      last = i - 1
      break
    end
  end

  return first, last, lines
end

function M.cell()
  local first, last, lines = M.cell_range()
  return vim.list_slice(lines, first, last)
end

function M.file()
  return vim.api.nvim_buf_get_lines(0, 0, -1, false)
end

--- Whether a cell has anything to run, rather than only comments and blanks.
local function has_code(lines)
  for _, line in ipairs(lines) do
    if line:match("%S") and not line:match("^%s*#") then
      return true
    end
  end
  return false
end

--- The cells from line 1 to ``stop``, markers left out, each as
--- { line = where it starts, lines = its code }. Cells with no code are skipped.
function M.cells(stop)
  local lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
  stop = math.min(stop or #lines, #lines)
  local cells = {}
  local start, body = 1, {}
  local function close()
    if has_code(body) then
      table.insert(cells, { line = start, lines = body })
    end
  end
  for i = 1, stop do
    if M.is_marker(lines[i]) then
      close()
      start, body = i, {}
    else
      table.insert(body, lines[i])
    end
  end
  close()
  return cells
end

local function send(lines)
  if lines == nil or #lines == 0 then
    return
  end
  M.last = { method = "pystudio_send", payload = lines }
  vim.rpcnotify(chan, "pystudio_send", lines)
end

--- Send cells as separate executions, which pystudio runs in order and stops
--- at the first that fails, rather than as one block that a single error or
--- typo would stop as a whole.
local function send_cells(cells)
  if #cells == 0 then
    return
  end
  M.last = { method = "pystudio_send_cells", payload = cells }
  vim.rpcnotify(chan, "pystudio_send_cells", cells)
end

--- Send the visual selection, or the line under the cursor, then advance.
function M.send_line()
  local lines, bottom
  if in_visual_mode() then
    local mode = vim.fn.mode()
    local anchor = vim.fn.getpos("v")
    local head = vim.fn.getpos(".")
    lines = vim.fn.getregion(anchor, head, { type = mode })
    -- Advance past the end of the selection whichever way it was made; the
    -- cursor sits at the start of an upward selection.
    bottom = math.max(anchor[2], head[2])
    vim.cmd("normal! \27") -- <Esc> now, rather than queued through nvim_input
  else
    lines = { vim.api.nvim_get_current_line() }
    bottom = vim.fn.line(".")
  end
  send(lines)
  if bottom < vim.api.nvim_buf_line_count(0) then
    goto_line(bottom + 1)
  end
end

--- Send the current cell, then move to the first line of the next one.
function M.send_cell()
  local first, last, lines = M.cell_range()
  send(vim.list_slice(lines, first, last))
  for i = last + 1, #lines do
    if M.is_marker(lines[i]) then
      goto_line(i + 1)
      return
    end
  end
end

--- The whole buffer, cell by cell.
function M.send_file()
  send_cells(M.cells())
end

--- Every cell above the current one, cell by cell: what a restart has to replay.
function M.send_above()
  local first = M.cell_range()
  send_cells(M.cells(first - 1))
end

--- From the cursor to the end of the buffer.
function M.send_to_end()
  local lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
  local cursor = vim.api.nvim_win_get_cursor(0)[1]
  send(vim.list_slice(lines, cursor, #lines))
end

function M.send_last()
  if M.last ~= nil then
    vim.rpcnotify(chan, M.last.method, M.last.payload)
  end
end

local function control(what)
  vim.rpcnotify(chan, "pystudio_control", what)
end

-- Keymaps. <localleader> is `\` unless the user set one; when they have a
-- separate <leader>, the same keys are offered there too, but never on top of a
-- mapping they already made.
local function literal(lhs)
  local leader = vim.g.mapleader or "\\"
  local localleader = vim.g.maplocalleader or "\\"
  local out = lhs:gsub("<leader>", function()
    return leader
  end)
  out = out:gsub("<localleader>", function()
    return localleader
  end)
  return out
end

M.keys = {}
M.skipped = {}

--- True when a key is already spoken for, as a whole or as a prefix.
---
--- Prefixes matter in both directions: `<leader>f` would shadow an existing
--- `<leader>ff`, making the user wait out `timeoutlen` for their own mapping,
--- and an existing `<leader>f` would swallow a `<leader>ff` of ours.
local function taken(lhs)
  local target = literal(lhs)
  for _, keymap in ipairs(vim.api.nvim_get_keymap("n")) do
    local existing = keymap.lhs
    local shared = math.min(#existing, #target)
    if existing:sub(1, shared) == target:sub(1, shared) then
      return true
    end
  end
  return false
end

local function map(suffix, rhs, desc)
  local candidates = { "<localleader>" .. suffix }
  local leader = vim.g.mapleader
  if leader and leader ~= (vim.g.maplocalleader or "\\") then
    table.insert(candidates, "<leader>" .. suffix)
  end
  for _, lhs in ipairs(candidates) do
    if taken(lhs) then
      table.insert(M.skipped, literal(lhs))
    else
      vim.keymap.set({ "n", "x" }, lhs, rhs, { desc = "pystudio: " .. desc })
      table.insert(M.keys, literal(lhs))
    end
  end
end

map("l", M.send_line, "send line or selection")
map("c", M.send_cell, "send cell and advance")
map("f", M.send_file, "send file")
map("a", M.send_above, "send everything above this cell")
map("e", M.send_to_end, "send cursor to end of file")
map(".", M.send_last, "send the last thing again")
-- Terminals collapse <C-CR> into <CR> unless the kitty keyboard protocol is on,
-- so this is an alias rather than the documented default.
vim.keymap.set({ "n", "x" }, "<C-CR>", M.send_line, { desc = "pystudio: send line" })

local commands = {
  PyStudioSend = { M.send_line, "Send line or selection" },
  PyStudioSendCell = { M.send_cell, "Send cell and advance" },
  PyStudioSendFile = { M.send_file, "Send file" },
  PyStudioSendAbove = { M.send_above, "Send everything above this cell" },
  PyStudioSendToEnd = { M.send_to_end, "Send cursor to end of file" },
  PyStudioSendLast = { M.send_last, "Send the last thing again" },
  PyStudioInterrupt = {
    function()
      control("interrupt")
    end,
    "Interrupt the kernel",
  },
  PyStudioRestart = {
    function()
      control("restart")
    end,
    "Restart the kernel",
  },
}

for name, spec in pairs(commands) do
  vim.api.nvim_create_user_command(name, spec[1], { desc = spec[2] })
end

-- Let the status bar follow the buffer, and let a user's own statusline know it
-- is running inside pystudio.
vim.g.pystudio = true
vim.g.pystudio_keys = M.keys
vim.g.pystudio_keys_skipped = M.skipped
vim.api.nvim_create_augroup("pystudio", { clear = true })
vim.api.nvim_create_autocmd({ "BufEnter", "BufWritePost" }, {
  group = "pystudio",
  callback = function(args)
    vim.rpcnotify(chan, "pystudio_buffer", vim.api.nvim_buf_get_name(args.buf))
  end,
})

_G.pystudio = M
return true
