-- Live reload: when a file open in a buffer changes on disk, as it does when a
-- coding agent edits it, the buffer follows at once rather than at the next
-- focus change.
--
-- Each file buffer gets a libuv watcher on its path. Writers often replace a
-- file by renaming over it, which ends a watcher, so every event re-arms it.
-- A reload is an ordinary undo step (see 'undoreload'), so `u` takes it back.

local uv = vim.uv or vim.loop
local DEBOUNCE_MS = 50
local MODIFIED_WARNING = "changed on disk; unsaved edits kept (:e! reloads)"

local watchers = {}

vim.o.autoread = true

local function stop(buf)
  local watcher = watchers[buf]
  if watcher ~= nil then
    watcher.handle:stop()
    watcher.handle:close()
    if watcher.timer ~= nil then
      watcher.timer:stop()
      watcher.timer:close()
    end
    watchers[buf] = nil
  end
end

local watch

local function changed(buf)
  if not vim.api.nvim_buf_is_valid(buf) then
    stop(buf)
    return
  end
  vim.cmd("checktime " .. buf)
  -- A rename leaves the old watcher on a file that is gone; start over on the path.
  watch(buf)
end

watch = function(buf)
  stop(buf)
  if vim.bo[buf].buftype ~= "" then
    return
  end
  local path = vim.api.nvim_buf_get_name(buf)
  if path == "" or uv.fs_stat(path) == nil then
    return
  end
  local handle = uv.new_fs_event()
  if handle == nil then
    return
  end
  local watcher = { handle = handle }
  watchers[buf] = watcher
  handle:start(path, {}, function(err)
    if err ~= nil then
      return
    end
    if watcher.timer == nil then
      watcher.timer = uv.new_timer()
    end
    watcher.timer:stop()
    watcher.timer:start(DEBOUNCE_MS, 0, vim.schedule_wrap(function()
      if watchers[buf] == watcher then
        changed(buf)
      end
    end))
  end)
end

local group = vim.api.nvim_create_augroup("pystudio_reload", { clear = true })

vim.api.nvim_create_autocmd({ "BufReadPost", "BufWritePost", "BufFilePost" }, {
  group = group,
  callback = function(args)
    watch(args.buf)
  end,
})

vim.api.nvim_create_autocmd({ "BufDelete", "BufWipeout" }, {
  group = group,
  callback = function(args)
    stop(args.buf)
  end,
})

-- Without this Neovim would ask, blocking the editor until the user answered.
vim.api.nvim_create_autocmd("FileChangedShell", {
  group = group,
  callback = function(args)
    if vim.v.fcs_reason == "deleted" then
      vim.v.fcs_choice = ""
      return
    end
    if vim.bo[args.buf].modified then
      vim.v.fcs_choice = ""
      -- Kept short and out of the message history: a message wider than the
      -- command line raises a hit-enter prompt, which blocks the editor.
      vim.api.nvim_echo({ { MODIFIED_WARNING, "WarningMsg" } }, false, {})
      return
    end
    vim.v.fcs_choice = "reload"
  end,
})

for _, buf in ipairs(vim.api.nvim_list_bufs()) do
  if vim.api.nvim_buf_is_loaded(buf) then
    watch(buf)
  end
end

return true
