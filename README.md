# dotfiles

Cross-platform dotfiles managed with [chezmoi](https://www.chezmoi.io/).

## What's included

| Category | macOS | Windows | Both |
|----------|-------|---------|------|
| **Shell** | Fish, Zsh | PowerShell | — |
| **Prompt** | — | — | Starship |
| **Terminal** | Ghostty, iTerm2 | Windows Terminal (pwsh default) | — |
| **Version mgmt** | — | — | mise (agent CLIs, Python, Node) |
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

### Coding-agent CLIs

Claude Code, Codex, Grok Build, OpenCode, and RTK are installed through mise on macOS, Windows, and Linux. Versions are pinned in `~/.config/mise/config.toml`. Vendor self-updaters are disabled where present so mise remains the single update owner.

To bump a CLI, change the pin in that file and `chezmoi apply` (or `mise install`). Do not `mise upgrade` these tools — that ignores the pin. Do not use T3 Code’s provider update: mise-owned aqua installs are manual-only in T3, but a leftover Homebrew/npm/WinGet binary on PATH will be the one T3 upgrades.

`chezmoi apply` installs a missing pin when the tracked mise config changes.

When migrating an existing machine:

1. Apply, then confirm `mise which claude`, `mise which codex`, `mise which grok`, `mise which opencode`, and `mise which rtk`.
2. Remove Homebrew, npm, WinGet, or vendor-native copies that could shadow the mise shims.
3. Restart T3 Code and confirm each provider’s resolved binary is the mise shim (Windows: include a Start Menu launch). T3 one-click update should be unavailable (`update=null`) for those paths.

T3 is a launcher. It does not install these CLIs.

## How it works

- Files are stored in chezmoi's source format (`dot_` prefix replaces leading `.`)
- Files ending in `.tmpl` are [Go templates](https://www.chezmoi.io/user-guide/templating/) with OS-conditional logic
- `modify_` templates merge a small invariant into a tool-owned config file without replacing the rest of the file
- `.chezmoiignore` controls which files deploy on which OS
- `fish_variables` is intentionally not managed — Fish manages it automatically; important variables are set in `config.fish`
