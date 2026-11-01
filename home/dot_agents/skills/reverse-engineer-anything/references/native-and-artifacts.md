# Native analysis

## Ghidra on macOS

`tools-re` declares Ghidra in `~/.config/reverse-engineering/Brewfile`, independently of the baseline `packages` module. Its Homebrew formula installs the host-native decompiler and the required JDK. To install or restore missing packages when provisioning is in scope:

```sh
brew bundle --file="$HOME/.config/reverse-engineering/Brewfile" --no-upgrade
```

`--no-upgrade` suppresses explicit upgrades; Homebrew may still update dependencies required to install a missing package.

Choose a reusable project-storage location with no path component starting with `.`. Ghidra 12.2 rejects hidden components such as `.t3`, `.cache`, or `.local` with `Path element starting with '.' is not permitted`. For a T3 worktree, keep the Ghidra project outside it, for example under `$HOME/ghidra-projects`, and record the project location and name in the investigation's findings. Explicitly selected input binaries and scripts can stay in the worktree.

`ghidraRun` launches the GUI with Homebrew's JDK selection, but its wrapper sets `JAVA_HOME` only for that launch. Calling `support/analyzeHeadless` directly bypasses the wrapper; select the JDK explicitly in each headless shell invocation. After writing a post-script for the requested output, run:

```sh
ghidra_install="$(brew --prefix ghidra)/libexec"
ghidra_java_major="$(sed -n 's/^application.java.min=//p' "$ghidra_install/Ghidra/application.properties")"
ghidra_java_home="$(brew --prefix "openjdk@$ghidra_java_major")/libexec/openjdk.jdk/Contents/Home"
ghidra_projects="$HOME/ghidra-projects"
mkdir -p "$ghidra_projects"

JAVA_HOME="$ghidra_java_home" "$ghidra_install/support/analyzeHeadless" \
  "$ghidra_projects" Investigation \
  -import /absolute/path/to/binary \
  -scriptPath /absolute/script-directory -postScript ExportFindings.java
```

Java scripts extend `ghidra.app.script.GhidraScript`. Use `currentProgram` for functions, references, symbols, and listing; use `ghidra.app.decompiler.DecompInterface` for pseudocode. Check `openProgram(currentProgram)` and `decompileCompleted()`, then verify that `getDecompiledFunction()` is non-null before calling `getC()`. Record functions without pseudocode and dispose the decompiler afterward. Consult the installed `support/analyzeHeadlessREADME.md` for exact launcher options.

Keep the project to reuse its analysis. Later runs can select the imported program with `-process PROGRAM_NAME -noanalysis`, together with a focused post-script. Use `-deleteProject` only for a disposable project created by this investigation. Importing or decompiling the binary does not execute it.

On other hosts, locate the machine's declared Ghidra installation and matching JDK. This dotfiles module currently provisions the native engine on macOS only.

## REA as an optional driver

For REA, pass `GHIDRA_INSTALL_DIR` and `JAVA_HOME` for that invocation. On macOS, inspect the installation and JDK selection in the same shell call as the provider check:

```sh
ghidra_install="$(brew --prefix ghidra)/libexec"
ghidra_java_major="$(sed -n 's/^application.java.min=//p' "$ghidra_install/Ghidra/application.properties")"
ghidra_java_home="$(brew --prefix "openjdk@$ghidra_java_major")/libexec/openjdk.jdk/Contents/Home"
GHIDRA_INSTALL_DIR="$ghidra_install" JAVA_HOME="$ghidra_java_home" rea providers --format json
```

Check the Ghidra entry in `analysis_provider_candidates`: `availability.status` and `availability.code` describe whether REA admits the installed engine. Inspect failed entries in `availability.diagnostics.checks` before choosing a remedy. If the Ghidra `version` check reports `unsupported_version`, use direct Ghidra analysis; change the REA pin through dotfiles when a compatible release is available. If the `java` check reports `unsupported_version`, select a supported 64-bit full JDK and rerun the provider check. When the provider is available, inspect `rea decompile --help`, `rea function --help`, or `rea decompile-all --help` and pass the same environment with the selected command.

REA's Ghidra sessions use temporary projects and discard them on close. Its `--snapshot` stores cached analysis results rather than an editable Ghidra project. For many related functions, prefer a batch export or a reusable direct project.
