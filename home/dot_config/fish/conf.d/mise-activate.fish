# Intentionally shadows Homebrew's vendor_conf.d/mise-activate.fish.
# Fish sources vendor_conf.d/*.fish before config.fish, so in clean GUI/launchd
# environments where MISE_FISH_AUTO_ACTIVATE is unset, the vendor snippet would
# activate mise before config.fish adds ~/.cargo/bin—leaving ~/.cargo/bin ahead
# of ~/.local/share/mise/command-wrappers/bin. config.fish activates mise
# explicitly after adding ~/.cargo/bin.
