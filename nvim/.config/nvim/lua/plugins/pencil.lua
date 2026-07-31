-- lua/plugins/pencil.lua
return {
  {
    "preservim/vim-pencil",
    ft = { "markdown", "text", "tex" },  -- lazy-load only for prose filetypes
    init = function()
      -- Soft wrap keeps each paragraph as ONE logical line on disk.
      -- This is what Obsidian (desktop + Boox app) and Pandoc expect.
      vim.g["pencil#wrapModeDefault"] = "soft"
      vim.g["pencil#textwidth"] = 74          -- only used in hard-wrap mode
      vim.g["pencil#conceallevel"] = 2         -- hide markup like **bold** markers
      vim.g["pencil#concealcursor"] = "c"      -- but reveal on the cursor line
      vim.g["pencil#autoformat"] = 1
    end,
    config = function()
      local grp = vim.api.nvim_create_augroup("PencilProse", { clear = true })
      vim.api.nvim_create_autocmd("FileType", {
        group = grp,
        pattern = { "markdown", "text", "tex" },
        callback = function()
          vim.fn["pencil#init"]({ wrap = "soft" })
          -- prose-friendly buffer-local options
          vim.opt_local.spell = true
          vim.opt_local.spelllang = "en_us"
          vim.opt_local.linebreak = true       -- wrap at word boundaries
          vim.opt_local.wrap = true
        end,
      })
    end,
  },
}
