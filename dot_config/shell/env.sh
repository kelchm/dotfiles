# ~/.config/shell/env.sh — shared environment for sh-family shells (zsh, bash, sh)
# on macOS and Linux. Windows uses PowerShell ($PROFILE) and never sources this.
# Sourced by .zshenv / .profile / .bashrc / .bash_profile. fish has its own config.fish.
#
# Rules: POSIX only (no arrays / `path=()`), quiet (no output — sourced by non-interactive
# shells too), and idempotent (may be sourced multiple times per shell; must not grow or
# reorder PATH).

# Move $1 to the FRONT of PATH, removing any existing occurrence(s) first so precedence is
# deterministic regardless of what the parent shell already had (not merely "add if
# missing", which leaves inherited entries stuck in the wrong order). No-op if $1 isn't a
# dir. Pure POSIX parameter expansion — matches $1 literally and works the same in
# zsh/bash/sh (zsh does not word-split unquoted $PATH, so we never iterate it). Call
# LOWEST-priority dirs first; the last call ends up first.
path_prepend() {
    [ -d "$1" ] || return 0
    _pp=":$PATH:"
    while case "$_pp" in *":$1:"*) : ;; *) false ;; esac; do
        _pp="${_pp%%:"$1":*}:${_pp#*:"$1":}"
    done
    _pp="${_pp#:}"; _pp="${_pp%:}"
    PATH="$1${_pp:+:$_pp}"
    unset _pp
}

# Homebrew — Apple Silicon mac (/opt/homebrew) or Linuxbrew. Detect the first prefix that
# exists; only fork `brew shellenv` when brew isn't already on PATH (keeps repeat shells
# cheap while STILL recovering a bare/truncated PATH even if HOMEBREW_PREFIX was inherited).
# Force the `bash` dialect: with no arg, brew guesses from the parent process / $SHELL and
# can emit fish syntax into a POSIX shell (breaks under sandboxed agents where $SHELL=fish
# and process detection fails). `bash` output is plain `export ...`, valid in zsh/bash/sh.
for _brew in /opt/homebrew /home/linuxbrew/.linuxbrew "$HOME/.linuxbrew"; do
    [ -x "$_brew/bin/brew" ] || continue
    case ":$PATH:" in
        *":$_brew/bin:"*) ;;                            # already on PATH — skip the fork
        *) eval "$("$_brew/bin/brew" shellenv bash)" ;;
    esac
    break
done
unset _brew

# Precedence (highest first): ~/.local/bin > mise shims > cargo > brew > system.
# Listed low-to-high because path_prepend moves each to the front.
#
# Rust: cargo/rustc resolve via the mise shims. mise's rust backend delegates to rustup,
# so ~/.cargo/bin holds rustup's proxies (cargo -> rustup, ...) plus `cargo install`
# binaries — kept below the shims so mise stays authoritative for per-repo switching via
# rust-toolchain.toml. (We deliberately don't source rustup's ~/.cargo/env.)
[ -n "${HOMEBREW_PREFIX:-}" ] && { path_prepend "$HOMEBREW_PREFIX/sbin"; path_prepend "$HOMEBREW_PREFIX/bin"; }
path_prepend "$HOME/.cargo/bin"
path_prepend "$HOME/.local/share/mise/shims"
path_prepend "$HOME/.local/bin"

export PATH

# 1Password SSH agent — macOS socket. Export only when it exists so this never points ssh
# at a dead path on Linux/Windows. (Linux 1Password uses a different socket; deferred.)
_op_sock="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
[ -S "$_op_sock" ] && export SSH_AUTH_SOCK="$_op_sock"
unset _op_sock

# Claude Code — fold the loose ~/.claude.json (and its lock/tmp litter) into ~/.claude.
# Pointing at the default fallback dir is deliberate: components that ignore the variable
# fall back to ~/.claude anyway, so everything converges on one place. Shell-scoped only;
# Dock-launched GUI apps won't see it, and their worst case is recreating the loose file
# (the pre-variable status quo). Windows sets this at the user-registry level instead.
export CLAUDE_CONFIG_DIR="$HOME/.claude"
