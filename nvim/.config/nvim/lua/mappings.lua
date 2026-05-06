require "nvchad.mappings"

-- add yours here

local map = vim.keymap.set

-- Override NvChad's C-h/j/k/l with tmux navigator
map("n", "<C-h>", "<cmd>TmuxNavigateLeft<cr>", { desc = "Tmux navigate left" })
map("n", "<C-j>", "<cmd>TmuxNavigateDown<cr>", { desc = "Tmux navigate down" })
map("n", "<C-k>", "<cmd>TmuxNavigateUp<cr>", { desc = "Tmux navigate up" })
map("n", "<C-l>", "<cmd>TmuxNavigateRight<cr>", { desc = "Tmux navigate right" })

-- =============================================
-- Claude Code in a terminal split
-- =============================================

vim.g.claude_buf = nil
vim.g.claude_win = nil

local function toggle_claude()
  -- If window exists and is valid, close it
  if vim.g.claude_win and vim.api.nvim_win_is_valid(vim.g.claude_win) then
    vim.api.nvim_win_close(vim.g.claude_win, true)
    vim.g.claude_win = nil
    return
  end

  -- Open a vertical split on the right
  vim.cmd("botright vsplit")
  local win = vim.api.nvim_get_current_win()
  vim.g.claude_win = win

  -- Set width to ~40% of editor
  local width = math.floor(vim.o.columns * 0.4)
  vim.api.nvim_win_set_width(win, width)

  -- Reuse existing buffer or create new terminal
  if vim.g.claude_buf and vim.api.nvim_buf_is_valid(vim.g.claude_buf) then
    vim.api.nvim_win_set_buf(win, vim.g.claude_buf)
  else
    vim.cmd("terminal claude --dangerously-skip-permissions")
    vim.g.claude_buf = vim.api.nvim_get_current_buf()
  end

  -- Clean up terminal UI
  vim.wo[win].number = false
  vim.wo[win].relativenumber = false
  vim.wo[win].signcolumn = "no"

  -- Enter insert mode so you can type immediately
  vim.cmd("startinsert")
end

map("n", "<leader>cc", toggle_claude, { desc = "Toggle Claude Code" })

-- Send visual selection to Claude Code terminal
map("v", "<leader>cs", function()
  vim.cmd('normal! "zy')
  local text = vim.fn.getreg("z")

  if vim.g.claude_buf and vim.api.nvim_buf_is_valid(vim.g.claude_buf) then
    local chan = vim.bo[vim.g.claude_buf].channel
    if chan then
      vim.fn.chansend(chan, text)
    end
  else
    vim.notify("Claude Code terminal not open. Use <leader>cc first.", vim.log.levels.WARN)
  end
end, { desc = "Send selection to Claude" })

-- Yank file paths (paste into Claude for context)
map("n", "<leader>yr", function()
  local path = vim.fn.fnamemodify(vim.fn.expand("%"), ":.")
  vim.fn.setreg("+", path)
  vim.notify("Copied: " .. path)
end, { desc = "Yank relative path" })

map("n", "<leader>ya", function()
  local path = vim.fn.expand("%:p")
  vim.fn.setreg("+", path)
  vim.notify("Copied: " .. path)
end, { desc = "Yank absolute path" })

-- =============================================
-- Terminal navigation
-- =============================================

-- Escape terminal mode
map("t", "<C-\\>", "<C-\\><C-n>", { desc = "Exit terminal mode" })

-- Navigate between splits from terminal mode
map("t", "<C-h>", "<C-\\><C-n><C-w>h", { desc = "Move to left split" })
map("t", "<C-l>", "<C-\\><C-n><C-w>l", { desc = "Move to right split" })
map("t", "<C-j>", "<C-\\><C-n><C-w>j", { desc = "Move to split below" })
map("t", "<C-k>", "<C-\\><C-n><C-w>k", { desc = "Move to split above" })

map("t", "<S-CR>", "<CR>", { desc = "Newline in terminal" })

-- =============================================
-- Diagnostics
-- =============================================
map("n", "<leader>e", vim.diagnostic.open_float, { desc = "Show diagnostic" })
map("n", "[d", vim.diagnostic.goto_prev, { desc = "Prev diagnostic" })
map("n", "]d", vim.diagnostic.goto_next, { desc = "Next diagnostic" })

map("n", ";", ":", { desc = "CMD enter command mode" })
map("i", "jk", "<ESC>")

-- map({ "n", "i", "v" }, "<C-s>", "<cmd> w <cr>")
