# Profiles and ownership

A profile supplies module defaults on initialization. Every resulting switch is saved in the machine's chezmoi config, including both `true` and `false`. Later changes to a profile's defaults do not reset those machine choices; newly introduced modules receive their profile defaults on reinitialization.

| Module | Owns | Standalone | Omarchy |
| --- | --- | --- | --- |
| `desktop` | Personal Hyprland input/appearance overrides (Omarchy only) | Off | Off |
| `git` | Personal Git include, its include block, and a bounded 1Password block in SSH config (the `git` module owns both) | On | On |
| `agents` | Shared instructions/skills and the OpenCode Go provider invariant | On | On |
| `tools` | mise harnesses, gh, uv, updater environment, harness update task | On | On |
| `runtimes` | Global Node LTS, Python 3.12, Python environment and Rust version-file settings | On | Off |
| `shell` | Bash/Zsh/Fish/PowerShell startup files and shared shell environment | On | Off |
| `prompt` | Personal Starship configuration | On | Off |
| `terminal` | Ghostty, iTerm2, Windows Terminal, and T3 theme files | On | Off |
| `editor` | EditorConfig and shared VS Code preferences | On | Off |
| `packages` | Homebrew/WinGet package manifests | On | Off |

OS filtering applies after module selection. For example, enabling `terminal` on Linux adds Ghostty and the T3 theme, but never iTerm2 or Windows Terminal.

## Machine choices

Use `chezmoi edit-config` to edit `~/.config/chezmoi/chezmoi.toml` (the platform's chezmoi config directory on Windows). The editor comes from `$VISUAL`/`$EDITOR`, including Omarchy's configured editor. An Omarchy configuration starts with:

```toml
[data]
profile = "omarchy"
name = "Matthew Kelch"
email = "your-email@example.com"
signingMethod = "none"
signingKey = ""
sshAgent = "system"       # or "1password", independently of Git signing
bootstrap = true

[data.modules]
git = true
agents = true
tools = true
runtimes = false
shell = false
prompt = false
terminal = false
editor = false
packages = false
desktop = false
```

Set any switch and review `chezmoi diff` before applying. `runtimes` requires `tools`; `desktop` requires the `omarchy` profile. Disabling a module stops managing its targets and running its bootstrap scripts; it does not delete files already deployed or uninstall tools. To relinquish a managed key in mise, remove it from the local global config after disabling its owning module. There is no automatic destructive cleanup.

Changing `profile` alone does not reset persisted module choices. To adopt a new profile's defaults, remove `[data.modules]`, change the profile, and run `chezmoi init`. OS/profile and dependency checks run during initialization and ordinary rendering/apply, including after direct local-config edits.

## Bootstrap

`bootstrap = true` enables the existing ordered scripts, gated by their modules and OS:

1. Install Homebrew/WinGet packages (`packages`; no Linux package provisioning).
2. Install missing mise tools (`tools`). This does not upgrade existing versions.
3. Seed the macOS keychain token (`tools`; requires 1Password CLI access).
4. Select Fish as the macOS login shell (`shell`; may require sudo).
5. Remove legacy RTK hooks, global tool requests, and installations (`agents`; macOS/Windows only).
6. Install `github/gh-stack` if missing (`tools`), pinned to v0.2.0.

Set `bootstrap = false` to apply only configuration. `chezmoi apply --exclude scripts` also skips scripts for one invocation. Bootstrap scripts use `run_onchange_`; they run when their rendered contents change, rather than on every apply.

GitHub extension installation reports problems and lets apply continue. After fixing the problem, retry with:

```bash
mise exec -- gh extension install github/gh-stack --pin v0.2.0
```

Existing gh-stack installations are preserved. Updating an existing installation/pin is a separate manual action.

## Merge boundaries

Git reads Omarchy's `~/.config/git/config` before `~/.gitconfig`. A bounded include block at the beginning of `~/.gitconfig` loads `~/.config/git/dotfiles.gitconfig`. It overrides lower-priority XDG defaults; explicit machine settings and conditional includes later in `~/.gitconfig` keep their higher precedence. Existing credential helpers, conditional includes, and unrelated settings remain in place. Edit personal settings through the managed include; leave credential helpers and machine-specific preferences in the existing Git config. The include does not append another Windows credential helper.

The mise `modify_` template owns the declared shared keys, not the complete file. It preserves unrelated tools, settings, environment entries, and tasks. For a managed tool table it updates the version while retaining machine options such as `os`, `virtualenv`, and install environment. Alias migration carries those options to the selected tool name. Omarchy uses `gh` and `opencode`; standalone uses pinned `aqua:cli/cli` and explicit `npm:@opencode/cli` for compatibility with older registries. Switching profiles removes the alternate declarations for these same tools, but never uninstalls their old binaries. Check command resolution before manually removing duplicate installations.

On a change, the merge serializes TOML and removes comments. Once compliant, the original file is kept byte-for-byte. `upgrade.auto_prune = false` is enforced on every profile to keep upgrades from deleting directories used by running processes. Existing machine release-delay settings are preserved; `harness:update` explicitly bypasses them. New configurations have no release delay.

OpenCode's merge rule enables `opencode-go` when there is an allowlist and removes it from a denylist. Existing `opencode.json` and `opencode.jsonc` are both supported; missing files are left missing, so apply does not add a second global config. Local providers and default models stay local. A changed JSONC file is normalized to JSON; an already-compliant file keeps its comments. Connect providers once per machine; credentials are never in the repo.

Skills have one copy in `~/.agents/skills` and relative links for Claude, Codex, and Pi. Skill directories are additive: Omarchy's existing skill links and Codex's built-in `.system` directory remain in place. Agent settings, credentials, sessions, Pi model definitions, and OpenCode local providers remain machine-owned. The exception is the home-lab Sparks: `~/.pi/agent/extensions/spark.ts` lists whichever model they serve and registers nothing when they are unreachable.

## Extending the repo

1. Add the deployable file under `home/` using chezmoi's source naming, or run `chezmoi add` on its installed path.
2. Add its target path to the owning module in `home/.chezmoidata.toml`. Include the directory and `/**` for a whole directory.
3. Add OS ownership there if it is platform-specific. Use a merge template when the application owns unrelated settings in the same file.
4. Put reusable template fragments under `.chezmoitemplates/`, bootstrap scripts under `.chezmoiscripts/`, and tests/tooling outside `home/`.
5. Run the profile tests and review the rendered diff.

The opt-in `desktop` module owns only `input.lua` and `looknfeel.lua`. Main imports, bindings, monitors, and the rest of the desktop remain local. Keep packaged `/usr/share/omarchy` files and generated theme state out of this repo.

## Existing installations

Most files keep their deployed paths when their sources move into `home/`. Git changes ownership: the former fully managed `~/.gitconfig` becomes a machine-owned file with a managed include. Mise also changes from replacement to a merge.

After pulling this branch, run `chezmoi init` once to populate profile/module data, then inspect `chezmoi diff`. Init rewrites `chezmoi.toml` from the template, dropping anything outside `[data]` such as an `[edit]` command; set `$VISUAL`/`$EDITOR` instead. To choose the profile non-interactively, match the prompt text rather than the key: `chezmoi init --promptString "Configuration profile (standalone/omarchy)=standalone"`. Before the first apply, back up `~/.gitconfig` and remove settings previously supplied by this repo (identity, signing, init/push defaults, and Windows core preferences). Keep credential helpers and machine-specific conditional includes. The managed include supplies those personal preferences from now on. Otherwise old settings can remain active after their declarations are removed from the repo or override the new included defaults.

With `sshAgent = "1password"`, the `git` module appends a bounded `Host *` block that sets 1Password's `IdentityAgent`. Remove any hand-written equivalent from `~/.ssh/config` first. A duplicate still works, but it keeps 1Password active after switching to `sshAgent = "system"`.

The moved skill tests and theme generator are no longer deployed. Existing copies may be removed manually after checking for local modifications: `~/.agents/skills/t3-thread-search/tests/test_t3_thread_search.py`, `test_t3_thread_status.py` in the same directory, and `~/.config/t3code/themes/build-onedark-theme.mjs`.

macOS and Windows default to `standalone`, retaining the earlier shell and appearance setup. chezmoi tracks `run_onchange_` scripts by name, so the move under `.chezmoiscripts/` runs every enabled bootstrap script once more on the first apply, even where its content is unchanged. Expect `brew bundle` to upgrade outdated packages and the keychain seed to ask 1Password for access; existing gh extensions are preserved.
