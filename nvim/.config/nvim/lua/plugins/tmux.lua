return {
  {
    "christoomey/vim-tmux-navigator",
    lazy = false,
    -- Its <C-h/j/k/l> mappings are turned off so there is a single source of
    -- truth: after/plugin/herdr_nav.lua owns those keys and handles both
    -- multiplexers. It still calls this plugin's TmuxNavigate* commands when
    -- nvim is inside tmux rather than herdr, so tmux navigation is unchanged.
    init = function()
      vim.g.tmux_navigator_no_mappings = 1
    end,
  },
}
