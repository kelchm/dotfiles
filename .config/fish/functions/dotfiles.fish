function dotfiles --description "dotfiles commands with bare git repo"
  GIT_WORK_TREE=~ GIT_DIR=~/.dotfiles $argv
end