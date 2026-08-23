# Global instructions

## Delegating to another agent CLI

Grok (`grok`, grok-4.5) and Claude (`claude`) are available locally and already authenticated. Use the `delegate-review` skill for an independent second-pass review and the `delegate-implementation` skill for bounded, well-specified implementation work. Both skills carry the verified invocation contracts — do not improvise flags, and do not trust vendor docs over what those skills record.

Grok is the default delegate for bulk and mechanical work. Keep taste-sensitive work (public APIs, UI, copy) off the delegation path entirely.

A delegate CLI cannot run inside your sandbox — when `CODEX_SANDBOX` is set, request escalated permissions for that one command. The delegate needs its own home directory and network access, and it enforces its own read-only guard.

## Recursion guard

If `XDELEGATE_DEPTH` is set in the environment, **you are the callee in a delegated task**. Do the work yourself and do not delegate any part of it to another agent CLI — no `grok`, no `claude`, no `codex`, whether by bare name, absolute path, or any wrapper. Report your result and stop.

When you are the caller, always export `XDELEGATE_DEPTH=1` for the child process so the callee inherits this rule.
