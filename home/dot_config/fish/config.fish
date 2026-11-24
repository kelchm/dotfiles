# Environment — runs for every fish shell (interactive or not) so scripts get PATH too.
# Keep MISE_FISH_AUTO_ACTIVATE=0 for child shells; conf.d/mise-activate.fish
# shadows Homebrew's vendor_conf.d snippet in clean GUI/launchd environments.
set -gx MISE_FISH_AUTO_ACTIVATE 0

# Homebrew — Apple Silicon mac, Intel mac, or Linuxbrew. Use the fish dialect
# explicitly; a bare `brew shellenv` can misdetect the shell in a non-interactive
# spawn and emit POSIX syntax that fish can't parse (`${ is not a valid variable in fish`).
for brew_bin in /opt/homebrew/bin/brew /usr/local/bin/brew /home/linuxbrew/.linuxbrew/bin/brew $HOME/.linuxbrew/bin/brew
    if test -x $brew_bin
        $brew_bin shellenv fish | source
        break
    end
end

# Add ~/.cargo/bin (rustup proxies + `cargo install` bins) BEFORE `mise activate` so
# mise-managed toolchains and command wrappers (e.g. `mbx` for `cargo`) stay
# ahead of ~/.cargo/bin in both interactive and non-interactive fish shells. Use --move
# so inherited PATH entries still land in deterministic order; add ~/.local/bin last
# so it stays highest priority.
test -d $HOME/.cargo/bin; and fish_add_path -gPm $HOME/.cargo/bin
command -q mise; and mise activate fish | source
fish_add_path -gPm $HOME/.local/bin

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
