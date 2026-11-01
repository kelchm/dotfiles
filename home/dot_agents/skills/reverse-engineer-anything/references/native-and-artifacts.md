# Native analysis

## Ghidra on macOS

`tools-re` declares Ghidra in `~/.config/reverse-engineering/Brewfile`, independently of the baseline `packages` module. Its Homebrew formula installs the host-native decompiler and the required JDK. To install or restore missing packages when provisioning is in scope:

```sh
brew bundle --file="$HOME/.config/reverse-engineering/Brewfile" --no-upgrade
```

`ghidraRun` launches the GUI with Homebrew's JDK selection. For unattended analysis, choose a task-local project directory and write a Ghidra post-script for the requested output. After creating those paths, locate the headless launcher and set Java only for that invocation:

```sh
ghidra_install="$(brew --prefix ghidra)/libexec"
ghidra_java_major="$(sed -n 's/^application.java.min=//p' "$ghidra_install/Ghidra/application.properties")"
ghidra_java_home="$(brew --prefix "openjdk@$ghidra_java_major")/libexec/openjdk.jdk/Contents/Home"

JAVA_HOME="$ghidra_java_home" "$ghidra_install/support/analyzeHeadless" \
  /absolute/project-directory Investigation \
  -import /absolute/path/to/binary \
  -scriptPath /absolute/script-directory -postScript ExportFindings.java
```

Java scripts extend `ghidra.app.script.GhidraScript`. Use `currentProgram` for functions, references, symbols, and listing; use `ghidra.app.decompiler.DecompInterface` for pseudocode. Check `openProgram(currentProgram)` and `decompileCompleted()` before reading the C text, and dispose the decompiler afterward. Consult the installed `support/analyzeHeadlessREADME.md` for exact launcher options.

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

Check the Ghidra entry in `analysis_provider_candidates`: `availability.status` and `availability.code` describe whether REA admits the installed engine. If it reports `unsupported_version`, use direct Ghidra analysis; change the REA pin through dotfiles when a compatible release is available. When the provider is available, inspect `rea decompile --help`, `rea function --help`, or `rea decompile-all --help` and pass the same environment with the selected command.

REA's Ghidra sessions use temporary projects and discard them on close. Its `--snapshot` stores cached analysis results rather than an editable Ghidra project. For many related functions, prefer a batch export or a reusable direct project.
