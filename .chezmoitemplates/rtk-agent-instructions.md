## RTK

Prefix supported shell commands with `rtk` so command output is compressed before it hits context (`rtk git status`, `rtk rg PATTERN`, `rtk test`, `rtk lint`). If RTK has no filter, it passes through unchanged. Claude Code rewrites Bash automatically; still prefix `rtk` in Codex, Grok, and T3 if a rewrite hook does not fire.

Meta commands (always `rtk` directly): `rtk gain`, `rtk gain --history`, `rtk proxy <cmd>`. If `rtk gain` fails, the wrong `rtk` package is on PATH.
