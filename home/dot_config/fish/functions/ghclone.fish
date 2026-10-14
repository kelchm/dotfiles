function ghclone
    set -l repo_url $argv[1]
    set -l base_dir ~/Development
    set -l editor_cmd code
    set -l open_in_editor false
    set -l auto_dir_switch true

    for arg in $argv
        switch $arg
            case '-e' '--edit'
                set open_in_editor true
            case '-d' '--no-dir-switch'
                set auto_dir_switch false
        end
    end

    if test -z "$repo_url"
        echo "Usage: ghclone <repository-url> [-e/--edit] [-d/--no-dir-switch]"
        return 1
    end

    set -l repo_path (string replace -r '.*:([^/]+)/(.+)\.git' '$1/$2' $repo_url)
    set -l full_path $base_dir/$repo_path

    echo "Cloning $repo_url to $full_path"
    git clone $repo_url $full_path

    if test $auto_dir_switch = true; and status --is-interactive
        cd $full_path
        echo "Switched to directory $full_path"
    end

    if test $open_in_editor = true
        $editor_cmd $full_path
    end
end
