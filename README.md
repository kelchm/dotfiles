# dotfiles

Personal development settings managed with [chezmoi](https://www.chezmoi.io/). Profiles choose a starting point; modules decide which configuration this repo owns.

- **`standalone`**: the existing macOS, Windows, or Linux environment, including shell and appearance preferences.
- **`omarchy`**: Git, agent instructions and skills, and mise-managed development tools. Omarchy owns the shell, prompt, terminals, desktop, and global runtime defaults.

## Setup

Install chezmoi, then initialize, review, and apply:

```bash
# macOS: brew install chezmoi
# Omarchy: omarchy pkg add chezmoi (mise is already installed)
chezmoi init kelchm
chezmoi diff
chezmoi apply
```

On Windows, install `twpayne.chezmoi` with WinGet, then use the same chezmoi commands in PowerShell. On ordinary Linux, install chezmoi and mise first; this repo does not provision the distribution.

Initialization suggests `omarchy` when `/usr/share/omarchy` exists; otherwise it suggests `standalone`. Git signing defaults to `none` on a new machine. Existing identity, signing, and module choices survive `chezmoi init`.

Customize this machine with `chezmoi edit-config`. The [profile guide](docs/profiles.md) covers module switches, bootstrap behavior, and configuration ownership; the [Omarchy guide](docs/omarchy.md) covers the local setup and 1Password integration.

## Everyday use

```bash
chezmoi diff                 # review rendered changes
chezmoi apply                # apply settings; bootstrap missing tools when config changes
mise install                 # restore missing tools
mise run harness:update      # update only Claude, Codex, Grok, OpenCode, and Pi
chezmoi edit ~/.config/git/dotfiles.gitconfig  # edit personal Git settings
```

`harness:update` bypasses release delays for those five tools. Runtime versions belong in project `mise.toml` files, or the optional global `runtimes` module. On Omarchy, `omarchy update` also updates mise tools.

## Repository layout

```text
home/                       chezmoi source root (.chezmoiroot points here)
  .chezmoidata.toml          profile defaults and module/OS target ownership
  .chezmoi.toml.tmpl         machine identity and persisted module choices
  .chezmoiscripts/           bootstrap and legacy cleanup scripts
  .chezmoitemplates/         shared agent text and modular mise declarations
  dot_*/                    deployable configuration and personal skills
scripts/                    repository tooling (theme generator)
tests/                      isolated profile checks and skill tests
docs/                       setup and ownership notes
```

[Adding configuration](docs/profiles.md#extending-the-repo) starts with assigning it to a module. Files outside `home/` are never deployed. Machine credentials, agent sessions, local model/provider settings, and generated Omarchy state stay outside source control.

## Validation

Requires chezmoi, Python 3.11+, Bash, Git, and an OpenSSH client:

```bash
python3 -m unittest discover -s tests
# Or set CHEZMOI=/path/to/chezmoi if it isn't on PATH.
```

Profile tests apply into temporary directories. They cover stock Omarchy preservation, module opt-outs, mise and OpenCode merges, SSH integration, and repeat applies. macOS and Windows branches are rendered on Linux; native package installation and PowerShell execution need their respective systems.
