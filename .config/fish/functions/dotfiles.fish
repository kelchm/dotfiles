function dotfiles
  command /opt/homebrew/bin/git --git-dir=$HOME/.dotfiles --work-tree=$HOME $argv;
end
