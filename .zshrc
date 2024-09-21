# .zshrc is sourced for interactive zsh shells
eval "$(starship init zsh)"
eval "$(/opt/homebrew/bin/mise activate zsh)"

# workaround for vscode devcontainers
export SSH_AUTH_SOCK=~/Library/Group\ Containers/2BUA8C4S2C.com.1password/t/agent.sock
