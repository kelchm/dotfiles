if status is-interactive
    # Commands to run in interactive sessions can go here
end

function starship_transient_prompt_func
#     # Defines which modules will show in transient prompt
    starship module line_break
    starship module line_break
    starship module container
    starship module shell
    starship module character
end

eval "$(/opt/homebrew/bin/brew shellenv)"
source /opt/homebrew/opt/asdf/libexec/asdf.fish
starship init fish | source
enable_transience
