return {
  {
    "stevearc/conform.nvim",
    event = "BufWritePre", -- uncomment for format on save
    opts = require "configs.conform",
  },

  -- These are some examples, uncomment them if you want to see them work!
  {
    "neovim/nvim-lspconfig",
    config = function()
      require "configs.lspconfig"
    end,
  },

  {
    "nvim-telescope/telescope.nvim",
    opts = {
      pickers = {
        live_grep = {
          additional_args = { "--hidden", "--glob", "!.git/", "--smart-case" },
        },
      },
    },
  },

-- lua/plugins/init.lua
  {
    "nvim-lualine/lualine.nvim",
    lazy = false, -- Load it at startup
    dependencies = { "nvim-tree/nvim-web-devicons" },
    config = function()
      require("lualine").setup({
        options = {
          theme = "solarized_dark", -- Matches your tmux/iterm2 theme
          component_separators = { left = "│", right = "│" },
          section_separators = { left = "", right = "" }, -- The "Lean" look
          globalstatus = true, -- High-end look: one bar for all splits
        },
        sections = {
          lualine_a = { "mode" },
          lualine_b = { "branch", "diff", "diagnostics" },
          lualine_c = {
            {
              function() return " " end,
              cond = function()
                -- Checks if 'claude' is in the current file path
                return string.find(vim.fn.expand("%:p"), "claude") ~= nil
              end,
              color = { fg = "#ed8796" }, -- Macchiato Maroon
            },
            { "filename", path = 1 }, 
          }, -- Shows relative path
          lualine_x = { "encoding", "fileformat", "filetype" },
          lualine_y = { "progress" },
          lualine_z = { "location" },
        },
      })
    end,
  },

  -- test new blink
  -- { import = "nvchad.blink.lazyspec" },

  -- {
  -- 	"nvim-treesitter/nvim-treesitter",
  -- 	opts = {
  -- 		ensure_installed = {
  -- 			"vim", "lua", "vimdoc",
  --      "html", "css"
  -- 		},
  -- 	},
  -- },
}
