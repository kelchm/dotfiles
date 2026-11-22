# Environment — runs for every fish shell (interactive or not) so scripts get PATH too.
set -gx MISE_FISH_AUTO_ACTIVATE 0

# Homebrew — Apple Silicon mac or Linuxbrew. Use the fish dialect explicitly; a bare
# `brew shellenv` can misdetect the shell in a non-interactive spawn and emit POSIX
# syntax that fish can't parse (`${ is not a valid variable in fish`).
for brew_bin in /opt/homebrew/bin/brew /home/linuxbrew/.linuxbrew/bin/brew $HOME/.linuxbrew/bin/brew
    if test -x $brew_bin
        $brew_bin shellenv fish | source
        break
    end
end

# Add ~/.cargo/bin (rustup proxies + `cargo install` bins) BEFORE `mise activate` so
# mise-managed toolchains and command wrappers (e.g. `mbx` for `cargo` on macOS) stay
# ahead of ~/.cargo/bin in both interactive and non-interactive fish shells. Add
# ~/.local/bin last so it stays highest priority.
test -d $HOME/.cargo/bin; and fish_add_path -gP $HOME/.cargo/bin
mise activate fish | source
fish_add_path -gP $HOME/.local/bin

# 1Password SSH agent — only when the macOS socket exists (absent on Linux/Windows).
set -l op_sock "$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
test -S "$op_sock"; and set -gx SSH_AUTH_SOCK "$op_sock"

# Interactive-only: prompt. Pointless (and slightly wasteful) in non-interactive fish.
if status is-interactive
    function starship_transient_prompt_func
        # Defines which modules will show in transient prompt
        starship module line_break
        starship module line_break
        starship module container
        starship module shell
        starship module character
    end
    starship init fish | source
    enable_transience
end
