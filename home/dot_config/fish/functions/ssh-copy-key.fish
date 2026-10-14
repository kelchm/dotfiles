function ssh-copy-key --description 'Interactively install one SSH-agent key on a remote host'
    if test (count $argv) -eq 0
        echo 'Usage: ssh-copy-key [ssh options] [user@]host' >&2
        return 2
    end

    if not type -q fzf
        echo 'ssh-copy-key: fzf is not installed or not on PATH' >&2
        return 127
    end

    set -l key (ssh-add -L 2>/dev/null | fzf \
        --no-multi \
        --with-nth=3.. \
        --prompt='SSH key> ' \
        --height='~40%' \
        --layout=reverse \
        --border)

    if test -z "$key"
        echo 'ssh-copy-key: no key selected' >&2
        return 1
    end

    printf '%s\n' "$key" | ssh $argv '
        umask 077
        mkdir -p "$HOME/.ssh" || exit 1
        touch "$HOME/.ssh/authorized_keys" || exit 1
        chmod 700 "$HOME/.ssh" || exit 1
        chmod 600 "$HOME/.ssh/authorized_keys" || exit 1
        IFS= read -r key || exit 1
        grep -Fqx "$key" "$HOME/.ssh/authorized_keys" ||
            printf "%s\n" "$key" >> "$HOME/.ssh/authorized_keys"
    '
end
