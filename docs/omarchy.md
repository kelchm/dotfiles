# Omarchy setup

The Omarchy profile adds personal development settings to the stock installation. It leaves Bash startup files, Starship, terminal themes, Hyprland, monitors, and desktop configuration with Omarchy.

```bash
omarchy pkg add chezmoi
chezmoi init kelchm            # choose omarchy
chezmoi diff
chezmoi apply
```

Omarchy already installs and activates mise. The profile keeps existing global runtimes such as Node, adds the shared harnesses plus gh/uv, and preserves unrelated tool declarations. Enable `runtimes` only if you want the repo's global Node LTS/Python 3.12 defaults; project-specific versions still take precedence.

## 1Password

For SSH authentication, enable the SSH agent in 1Password's developer settings, then set `sshAgent = "1password"` in chezmoi's `[data]` table and apply. Linux uses `~/.1password/agent.sock`. This works independently of the login shell or Git signing; the `git` module must be enabled because it owns the SSH config block too.

Enable the SSH agent in 1Password’s developer settings for signing too, then set:

```toml
[data]
# Keep the other identity/profile/module settings already in this table.
signingMethod = "ssh"
signingKey = "ssh-ed25519 YOUR_PUBLIC_KEY"
```

Then apply. When installed, 1Password's Linux signer at `/opt/1Password/op-ssh-sign` is selected. Only the public key is stored in local chezmoi data; private keys remain in 1Password. With `signingMethod = "none"`, the personal Git config disables commit signing by default. Explicit signing preferences later in the machine’s `~/.gitconfig` can override it.

The SSH merge appends a fallback `Host *` block to `~/.ssh/config`, so existing per-host agent choices (including `IdentityAgent none`) keep precedence. `sshAgent = "system"` removes only that block. On Windows, enable 1Password's named-pipe agent in the app; this repo does not configure a POSIX socket there.

## Launching and updating tools

The profile uses Omarchy's `claude`, `codex`, `opencode`, `pi`, and `gh` declarations. These `latest` settings agree with its first-run launchers, which can run `mise use -g`. Grok is installed through mise's `grok` registry backend; Omarchy's fallback wrapper uses a different npm backend. Use the activated shell or mise shims so the installed registry tool takes precedence. Current Omarchy registries resolve `opencode` to OpenCode 2's npm backend; on an older registry, update mise first.

Use the activated Bash shell or mise shims. GUI launchers outside an activated shell can use `mise exec -- <command>` so the managed updater environment is loaded.

```bash
mise install
mise run harness:update       # agent CLIs only; release delay bypassed
omarchy update                # normal system update, including mise tools
```

The dotfiles task leaves runtimes alone. Omarchy's full update may upgrade configured runtimes too. No custom desktop update hooks or packaged launcher replacements are needed.

## Desktop preferences in progress

An optional `desktop` module records the preferences currently being tested:

- Natural touchpad scrolling.
- Caps Lock as Ctrl, with Left Alt and Left Windows/Super swapped.
- A 1px window border.

The module is disabled by default. The Caps Lock mapping is provisional; review the committed override files against your desired keyboard behavior before enabling it.

Once settled, edit the source `home/dot_config/hypr/input.lua` and `looknfeel.lua`, set `desktop = true` under `[data.modules]`, and review the diff. These are plain source files; updated preferences follow the repo rather than being frozen in local initialization data. This replaces only the two personal override files, loaded after Omarchy's defaults. Preserve any further edits in those files before enabling the module. Monitor scale, output arrangement, and main Hyprland imports remain outside the module.

While changing desktop settings in another session, leave the module disabled or use `chezmoi re-add`/`chezmoi merge` to capture the final preferences before a full apply. Backups such as `input.lua.bak.*` are not managed.
