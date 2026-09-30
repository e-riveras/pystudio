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

local function is_marker(line)
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

--- Visual selection if there is one, otherwise the line under the cursor.
--- Leaves visual mode, so the caller can move the cursor afterwards.
function M.chunk()
  if in_visual_mode() then
    local mode = vim.fn.mode()
    local lines = vim.fn.getregion(vim.fn.getpos("v"), vim.fn.getpos("."), { type = mode })
    vim.cmd("normal! \27") -- <Esc> now, rather than queued through nvim_input
    return lines
  end
  return { vim.api.nvim_get_current_line() }
end

--- The lines between the nearest cell markers above and below the cursor.
function M.cell()
  local lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
  local cursor = vim.api.nvim_win_get_cursor(0)[1]

  local first = 1
  for i = cursor, 1, -1 do
    if is_marker(lines[i]) then
      first = i + 1
      break
    end
  end

  local last = #lines
  for i = cursor + 1, #lines do
    if is_marker(lines[i]) then
      last = i - 1
      break
    end
  end

  return vim.list_slice(lines, first, last)
end

function M.file()
  return vim.api.nvim_buf_get_lines(0, 0, -1, false)
end

local function send(lines)
  if lines == nil or #lines == 0 then
    return
  end
  vim.rpcnotify(chan, "pystudio_send", lines)
end

function M.send_line()
  send(M.chunk())
  if vim.fn.line(".") < vim.fn.line("$") then
    vim.cmd("normal! j") -- advance, the way RStudio's Ctrl+Enter does
  end
end

function M.send_cell()
  send(M.cell())
end

function M.send_file()
  send(M.file())
end

local function control(what)
  vim.rpcnotify(chan, "pystudio_control", what)
end

-- Keymaps. <localleader> is `\` unless the user set one.
local function map(lhs, rhs, desc)
  vim.keymap.set({ "n", "x" }, lhs, rhs, { desc = "pystudio: " .. desc })
end

map("<localleader>l", M.send_line, "send line or selection")
map("<localleader>c", M.send_cell, "send cell")
map("<localleader>f", M.send_file, "send file")
-- Terminals collapse <C-CR> into <CR> unless the kitty keyboard protocol is on,
-- so this is an alias rather than the documented default.
map("<C-CR>", M.send_line, "send line or selection")

vim.api.nvim_create_user_command("PyStudioSend", M.send_line, { desc = "Send line or selection" })
vim.api.nvim_create_user_command("PyStudioSendCell", M.send_cell, { desc = "Send cell" })
vim.api.nvim_create_user_command("PyStudioSendFile", M.send_file, { desc = "Send file" })
vim.api.nvim_create_user_command("PyStudioInterrupt", function()
  control("interrupt")
end, { desc = "Interrupt the kernel" })
vim.api.nvim_create_user_command("PyStudioRestart", function()
  control("restart")
end, { desc = "Restart the kernel" })

-- Let the status bar follow the buffer, and let a user's own statusline know it
-- is running inside pystudio.
vim.g.pystudio = true
vim.api.nvim_create_augroup("pystudio", { clear = true })
vim.api.nvim_create_autocmd({ "BufEnter", "BufWritePost" }, {
  group = "pystudio",
  callback = function(args)
    vim.rpcnotify(chan, "pystudio_buffer", vim.api.nvim_buf_get_name(args.buf))
  end,
})

_G.pystudio = M
return true
