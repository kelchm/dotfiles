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

For SSH authentication, enable the SSH agent in 1Password's developer settings, then set `sshAgent = "1password"` in chezmoi's `[data]` table and apply. Linux uses `~/.1password/agent.sock`. This works independently of the login shell or Git signing.

Enable the SSH agent in 1Password’s developer settings for signing too, then set:

```toml
[data]
# Keep the other identity/profile/module settings already in this table.
signingMethod = "ssh"
signingKey = "ssh-ed25519 YOUR_PUBLIC_KEY"
```

Then apply. When installed, 1Password's Linux signer at `/opt/1Password/op-ssh-sign` is selected. Only the public key is stored in local chezmoi data; private keys remain in 1Password. With `signingMethod = "none"`, the personal Git config explicitly disables commit signing, including a signing default inherited from another global config.

The SSH merge adds its own block at the top of `~/.ssh/config`, preserving existing host entries. `sshAgent = "system"` removes only that block. On Windows, enable 1Password's named-pipe agent in the app; this repo does not configure a POSIX socket there.

## Launching and updating tools

The profile uses Omarchy's `claude`, `codex`, `grok`, `opencode`, `pi`, and `gh` names. Their `latest` declarations agree with Omarchy's first-run launchers, which can run `mise use -g` when launched. Current Omarchy registries resolve `opencode` to OpenCode 2's npm backend; on an older registry, update mise first.

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

It is disabled by default and remains disabled on the prototype while the separate keyboard-setup thread is active. The Caps Lock mapping is provisional: Caps Lock as Super and other approaches are still being evaluated. No alternative remap has been adopted in the dotfiles.

Once settled, set `desktop = true` under `[data.modules]` and review the diff. `[data.desktop]` exposes `naturalScroll`, `keyboardOptions`, and `borderSize`; changing these machine values survives reinitialization. This replaces only the two personal override files, loaded after Omarchy's defaults. Preserve any further edits in those files before enabling the module. The machine's 1.25 monitor scale and main Hyprland imports remain outside the module.

While changing desktop settings in another session, leave the module disabled or use `chezmoi re-add`/`chezmoi merge` to capture the final preferences before a full apply. Backups such as `input.lua.bak.*` are not managed.

## Local prototype

The initial prototype was applied on this Omarchy machine with `git`, `agents`, and `tools` enabled, 1Password SSH authentication and Git signing enabled. The signing key matches GitHub’s existing “Personal - Signing” entry. A real commit was signed through 1Password and verified against that public key. ChezMoi itself was installed through mise as an additional machine-owned tool; the normal new-machine instructions above use Omarchy's package manager.

The source checkout is currently the working branch, selected by `sourceDir` in chezmoi's local config. Keep that checkout while testing. Once the PR is merged, it can be moved to the usual `~/.local/share/chezmoi` location; update `sourceDir` in the local config to match. Merely moving it without updating that setting breaks chezmoi commands.
