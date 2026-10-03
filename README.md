# dotfiles

Cross-platform dotfiles managed with [chezmoi](https://www.chezmoi.io/).

## What's included

| Category | macOS | Windows | Both |
|----------|-------|---------|------|
| **Shell** | Fish, Zsh | PowerShell | — |
| **Prompt** | — | — | Starship |
| **Terminal** | Ghostty, iTerm2 | Windows Terminal (pwsh default) | — |
| **Version mgmt** | — | — | mise (harness CLIs, Python, Node) |
| **Editor** | — | — | VSCode, EditorConfig |
| **Git** | 1Password SSH signing | Credential Manager | Common config |
| **SSH** | 1Password agent (socket) | 1Password agent (named pipe) | — |

## Install

### macOS

```bash
brew install chezmoi
chezmoi init --apply --ssh kelchm
```

Or as a one-liner on a fresh machine:

```bash
sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply --ssh kelchm
```

### Windows

```powershell
winget install twpayne.chezmoi
chezmoi init --apply --ssh kelchm
```

Or as a one-liner:

```powershell
irm get.chezmoi.io/ps1 | powershell -c - -- init --apply --ssh kelchm
```

## Usage

```bash
chezmoi edit ~/.config/starship.toml   # edit a managed file
chezmoi diff                            # preview pending changes
chezmoi apply                           # apply changes to home directory
chezmoi cd                              # cd into source directory
chezmoi add ~/.some/new/file            # start managing a new file
```

### Harness CLIs

Chezmoi bootstraps the configured tools; mise upgrades them. Harnesses track `latest`, so machines share configuration and an update method, but may have different versions until each is upgraded.

- Harness CLIs: Claude Code, Codex, Grok Build, OpenCode 2, Pi
- mise selects the installation backends using its registry defaults, except OpenCode 2, which is published only as the npm package `@opencode/cli` (the registry's `opencode` is still 1.x)
- Background self-updates are disabled through mise's environment settings

`minimum_release_age = "24h"` delays selection of timestamped releases. Grok's HTTP feed has no timestamps, so it is not covered. Already-installed versions are not downgraded.

```bash
chezmoi apply                                        # bootstrap tools when config changes
mise install                                         # restore missing configured tools
mise outdated claude codex grok npm:@opencode/cli pi # check these five tools
mise run harness:update                              # upgrade these five, leaving runtimes alone
```

Launch through mise shims or an activated shell so the updater settings are loaded. For scripts, use `mise exec -- <command>`. GUI launchers should use the shim path, rather than a versioned executable path.

OpenCode's `opencode.jsonc` merge rule keeps `opencode-go` available: it adds Go to an existing provider allowlist and removes it from any denylist. Other settings, including local providers and default models, stay machine-specific. If there is no allowlist, OpenCode already allows all connected providers. Connect Go once per machine with `/connect`; credentials are not stored in these dotfiles. When the rule changes a config, it normalizes JSONC to JSON and removes comments; an already-compliant config is left byte-for-byte unchanged.

On a machine that already had Homebrew, npm, or WinGet copies: apply, then remove those duplicate installations after checking that commands resolve through mise. The same applies to the OpenCode 1 copy mise installed earlier: once `opencode --version` reports 2.x, run `mise uninstall --all opencode`.

OpenCode 2 keeps the `opencode` command (and adds `opencode2`) and reads the same config files, so existing V1 settings carry over. V1 plugins and V1 server API clients do not; see the [migration guide](https://opencode.ai/v2/docs/migrate-v1/).

RTK is no longer used. On a machine that had it, the next `chezmoi apply` removes its Claude, Codex, and Pi hooks, its `RTK.md` files, the stale OpenCode plugin, and the binary. Its history and settings stay in RTK's own data directory (`~/Library/Application Support/rtk` on macOS); delete that by hand if you want it gone.

## How it works

- Files are stored in chezmoi's source format (`dot_` prefix replaces leading `.`)
- Files ending in `.tmpl` are [Go templates](https://www.chezmoi.io/user-guide/templating/) with OS-conditional logic
- `modify_` templates merge a small invariant into a tool-owned config file without replacing the rest of the file
- `.chezmoiignore` controls which files deploy on which OS
- `fish_variables` is intentionally not managed — Fish manages it automatically; important variables are set in `config.fish`
