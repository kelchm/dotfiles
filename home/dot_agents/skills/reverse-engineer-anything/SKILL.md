---
name: reverse-engineer-anything
description: Reverse engineer shipped binaries, firmware, application packages, or JavaScript; investigate requested runtime or browser behavior; and build AgentEnv bundles from recorded captures. Use normal repository tools when complete source answers the question.
---

# Reverse engineering

Use the CLI by default. Ghidra is the native decompiler; REA is an optional driver with artifact parsers, JavaScript analysis, and structured evidence. The shared setup does not register MCP, so missing MCP tools are expected. Continue through the CLI rather than repairing registration or asking for a restart. If a project explicitly opts into REA MCP, use its documented configuration and available tools without adding a global registration.

## Managed installation

Chezmoi owns this skill and the `tools-re` declarations. Mise owns the pinned `rea` CLI. On macOS, Homebrew owns Ghidra and its JDK through `~/.config/reverse-engineering/Brewfile`. Use those declarations to install or restore tools when provisioning is in scope. Bootstrap runs on first apply and when the corresponding declarations change.

Changes to provisioning and versions belong in the dotfiles source. Do not repair this managed setup with `rea setup`, `rea update`, `rea uninstall`, or an ad hoc `npx` installation.

## Select the artifact and interface

Use the user's supplied path or resolve a named application to one clear installed artifact. Ask if the target remains ambiguous. Start with the package or resources when they answer the question; native code need not be the first layer.

- **Native executable or library:** use direct Ghidra analysis by default; read [native analysis](references/native-and-artifacts.md). REA's native driver is an option when its provider accepts the installed engine.
- **ASAR or extracted JavaScript/Electron tree:** use `rea analyze-javascript-application --help`, then analyze the supplied artifact. Native engines are unnecessary for this static route. Save large JSON results to a file and use `rea inspect-analysis-view --help` for focused follow-ups.
- **Firmware, archives, application resources, managed code, or another supported format:** inspect `rea --help` and the relevant command's help/schema. Prefer the smallest inspection that answers the question. Use standard local utilities when simpler.
- **Recorded captures or AgentEnv bundles:** inspect `rea inspect-web-network-capture --help` and `rea environment-build --help`. A retained capture can be analyzed offline; recorded URLs do not authorize fetching them. For a new browser capture, inspect `rea capture-browser-scenario --help` and keep the requested target and actions explicit.
- **Requested runtime or browser behavior:** choose a CLI operation appropriate to the question. Runtime commands can launch, attach to, or change the target. Check the command's help and relevant `rea capabilities`, perform only the requested actions, and confirm cleanup. Static decompilation does not observe execution.

Prefer the installed `rea`; use `mise exec -- rea ...` when shims are absent. Check the installed command's help rather than translating MCP tool names or assuming repository-main documentation describes the pinned release. JSON output is available with `--format json`. Inspect only relevant provider diagnostics; there is no need to run a global readiness check before every investigation.

REA's [release documentation](https://github.com/morluto/rea/tree/rea-agents-6.8.0/docs) can explain an operation, but this skill governs local installation and CLI use.

## Keep reusable evidence

Preserve the artifact identity, tool version, analysis settings, and saved results. Distinguish observed bytes, decompiler interpretations, and runtime observations. Keep coverage gaps explicit. Reuse an existing Ghidra project or matching saved results rather than repeatedly importing a large binary for individual questions. REA CLI snapshots cache previous answers; do not assume they preserve a live Ghidra database. Export related results together when practical.
