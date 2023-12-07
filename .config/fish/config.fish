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

# TODO: extract to another file!
set -gx HASS_SERVER "http://homeassistant.local:8123"
set -gx HASS_TOKEN "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI5ZTk2OGY1N2Q2ZWY0ZmMyOThjYzE2ODAwMTgxYzc1ZiIsImlhdCI6MTY3ODg0MTE0MSwiZXhwIjoxOTk0MjAxMTQxfQ.T1MtpggVlXPw_S8n5Veyyogom8V4admjdQKRNofHlsM"


eval "$(/opt/homebrew/bin/brew shellenv)"
source /opt/homebrew/opt/asdf/libexec/asdf.fish
starship init fish | source
enable_transience
