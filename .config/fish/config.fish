if status is-interactive
    # Commands to run in interactive sessions can go here
end

function starship_transient_prompt_func
    # Defines which modules will show in transient prompt
    starship module line_break
    starship module line_break
    starship module container
    starship module shell
    starship module character
end

# workaround for vscode devcontainers and 1password ssh-agent
# note: this needs to be set universally to override default macOS ssh-agent socket
set -U SSH_AUTH_SOCK ~/Library/Group\ Containers/2BUA8C4S2C.com.1password/t/agent.sock

# disable automatic activation of mise
set -Ux MISE_FISH_AUTO_ACTIVATE 0

eval "$(/opt/homebrew/bin/brew shellenv)"
mise activate fish | source
starship init fish | source
enable_transience
