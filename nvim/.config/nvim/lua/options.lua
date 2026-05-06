require "nvchad.options"

-- add yours here!
local o = vim.o

-- Auto-reload files changed on disk
o.autoread = true
vim.api.nvim_create_autocmd({ "FocusGained", "BufEnter", "CursorHold", "CursorHoldI" }, {
  callback = function()
    if vim.fn.mode() ~= "c" then
      vim.cmd("checktime")
    end
  end,
})

-- Notify on reload
vim.api.nvim_create_autocmd("FileChangedShellPost", {
  callback = function()
    vim.notify("File changed on disk. Buffer reloaded.", vim.log.levels.INFO)
  end,
})

vim.opt.laststatus = 3

-- Development defaults
o.relativenumber = true
o.scrolloff = 8
o.signcolumn = "yes"
o.updatetime = 250       -- faster CursorHold = faster autoread detection
o.undofile = true
o.clipboard = "unnamedplus"

