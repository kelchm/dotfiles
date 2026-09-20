# dotfiles

Cross-platform dotfiles managed with [chezmoi](https://www.chezmoi.io/).

## What's included

| Category | macOS | Windows | Both |
|----------|-------|---------|------|
| **Shell** | Fish, Zsh | PowerShell | — |
| **Prompt** | — | — | Starship |
| **Terminal** | Ghostty, iTerm2 | Windows Terminal (pwsh default) | — |
| **Version mgmt** | — | — | mise (harness CLIs, RTK, Python, Node) |
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

### Harness CLIs and RTK

Chezmoi bootstraps the configured tools; mise upgrades them. Harnesses track `latest`, so machines share configuration and an update method, but may have different versions until each is upgraded.

- Harness CLIs: Claude Code, Codex, Grok Build, OpenCode
- Filter (not an agent): RTK
- mise selects the installation backends using its registry defaults
- Background self-updates are disabled through mise's environment settings

`minimum_release_age = "24h"` delays selection of timestamped releases. Grok's HTTP feed has no timestamps, so it is not covered. Already-installed versions are not downgraded.

```bash
chezmoi apply                              # bootstrap tools when config changes
mise install                               # restore missing configured tools
mise outdated claude codex grok opencode rtk # check these five tools
mise run harness:update                    # upgrade these five, leaving runtimes alone
```

Launch through mise shims or an activated shell so the updater settings are loaded. For scripts, use `mise exec -- <command>`. GUI launchers should use the shim path, rather than a versioned executable path.

On a machine that already had Homebrew, npm, or WinGet copies: apply, then remove those duplicate installations after checking that commands resolve through mise.

## How it works

- Files are stored in chezmoi's source format (`dot_` prefix replaces leading `.`)
- Files ending in `.tmpl` are [Go templates](https://www.chezmoi.io/user-guide/templating/) with OS-conditional logic
- `modify_` templates merge a small invariant into a tool-owned config file without replacing the rest of the file
- `.chezmoiignore` controls which files deploy on which OS
- `fish_variables` is intentionally not managed — Fish manages it automatically; important variables are set in `config.fish`
