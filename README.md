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

Claude Code, Codex, Grok Build, and OpenCode are installed and updated through
mise on macOS, Windows, and Linux. Vendor self-updaters are disabled where
present so mise remains the single update owner.

```bash
mise run agent-clis:outdated  # check for newer releases
mise run agent-clis:update    # update all four CLIs
```

`chezmoi apply` installs missing versions when the tracked mise configuration
changes; it does not upgrade an unchanged `latest` declaration. Upgrades are
therefore explicit through the task above.

T3 Code does not currently recognize mise-managed provider installations. Do
not use its provider update action for these CLIs; update them through mise.

When migrating an existing machine, first apply and verify `mise which claude`,
`mise which codex`, `mise which grok`, and `mise which opencode`. Then remove any
older Homebrew, npm, or vendor-native installations that could shadow the mise
shims.

## How it works

- Files are stored in chezmoi's source format (`dot_` prefix replaces leading `.`)
- Files ending in `.tmpl` are [Go templates](https://www.chezmoi.io/user-guide/templating/) with OS-conditional logic
- `modify_` templates manage individual settings in tool-owned config files without replacing the rest of the file
- `.chezmoiignore` controls which files deploy on which OS
- `fish_variables` is intentionally not managed — Fish manages it automatically; important variables are set in `config.fish`
