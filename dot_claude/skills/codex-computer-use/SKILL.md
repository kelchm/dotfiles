---
name: codex-computer-use
description: Ask Codex CLI (gpt-5.5) to run local app verification that needs computer use, browser automation, simulators, screenshots, app launching, or independent runtime inspection. This is how gpt-5.5 is invoked for computer-use work. Use when the user asks Claude to have Codex or gpt-5.5 test a flow, verify UI behavior, inspect a running app, capture screenshots, or report confirmation and feedback about implemented behavior.
---

# Codex Computer Use

Use Codex as a separate local verification agent when the task needs real UI interaction, screenshots, simulator/browser/device state, or an independent runtime check outside Claude's current context.

Do not use this for ordinary code reading, typechecking, linting, or tests Claude can run directly. Launching apps, simulators, or browsers to verify the requested work is fine without asking; ask first only if the run could disrupt the user's environment beyond that (closing their apps, changing system settings, acting on real accounts or data).

## Workflow

1. State exactly what to verify and what "passing" looks like (the observable success criteria).
2. Create a temporary artifact directory for Codex's report and any screenshots.
3. Run `codex exec` with enough sandbox latitude to launch and drive the app/simulator/browser, and a focused verification prompt.
4. Read Codex's report and screenshots, and confirm the behavior before reporting it back.

```bash
ARTIFACT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/codex-cu.XXXXXX")"
REPORT="$ARTIFACT_DIR/report.md"
PROMPT="$ARTIFACT_DIR/prompt.md"

codex -C "$PWD" exec -s workspace-write - < "$PROMPT" > "$REPORT"
```

`workspace-write` covers launching local apps, simulators, and browsers. Only widen to `danger-full-access` if a specific run genuinely needs it, and say so first.

## Verification Prompt

```text
Verify <behavior> by actually running the app/flow — not by reading the code.

Steps:
- launch <app / simulator / browser> and drive <the flow>
- capture screenshots at <key states>
- report whether it matches <expected behavior>, and describe what you saw

Do not change code. If it fails, describe the failure and where it broke.
```

## Reporting Back

Relay what Codex actually observed, with its screenshots, separating confirmed behavior from anything it couldn't verify. If Codex reports a problem, confirm it's real before acting on it.

If `codex` is not installed or the command fails, report the error and offer to verify the behavior directly instead.
