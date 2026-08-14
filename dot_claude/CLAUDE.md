# Personal Preferences

## Commands
- Don't run dev server commans (e.g. `pnpm run dev`) start — assume it's already running unless instructed otherwise.
- Run read-only checks freely: lint, format, type-check, tests, `git diff`.

## Tooling
- Lean toward declarative, project-scoped, version-pinned configs over global machine state.
- Default to `mise` (`mise.toml`) for runtimes and tooling where it fits — pin versions rather than installing globally.
- macOS: Prefer mise's `aqua` backend when possible; `brew` is the macOS fallback when mise/aqua can't provide it.

## Code style
- Always strive for concise, simple solutions.
- If you see a simpler solution, propose it.

## General Asks
- If you are ever asked to do too much at once, stop and state that clearly.

## Language-specific Guidance

### Markdown
- Don't hard-wrap prose. Write each paragraph and list item as one unbroken line and let the renderer soft-wrap — *NO* manual line breaks at 80/100 columns.

### TypeScript
- Never use `any` unless 100% necessary or specifically instructed
- USe `pnpm` or `bun` -- never `npm`.


## Picking the right models for workflows and subagents

Rankings, higher = better. Cost is what I actually pay (grok-4.5 is very cheap for me right now due to a deal), not list price. Intelligence is how hard a problem you can hand the model unsupervised. Taste covers code quality, UI/UX, API design, and copy.

| model         | cost | intelligence | taste |
|---------------|------|--------------|-------|
| grok-4.5      | 9    | 8            | 6     |
| sonnet-5      | 5    | 5            | 7     |
| opus-4.8      | 4    | 7            | 8     |
| fable-5       | 2    | 9            | 9     |
| gpt-5.6-sol   | 6    | 7            | 6     |
| gpt-5.6-terra | 7    | 5            | 5     |
| gpt-5.6-luna  | 8    | 4            | 4     |

### Model Selection Guidance
- These are defaults, not limits. You have standing permission to escalate: if a cheaper model's output misses the bar, rerun or redo the work using a smarter model *without* asking. Always judge the output, not the price tag.
- Cost is a tie-breaker only; when axes conflict for anything that ships, intelligence > taste › cost.
- Implementation & bulk/mechanical work (clear-spec builds, migrations, refactors, data analysis): grok-4.5 is the default implementer — offload freely, including workflow implement stages. Fall back to gpt-5.6-sol (or a Claude model) when grok isn't a fit.
- Anything user-facing (UI, API design, copy) needs taste ≥ 7.
- Reviews of plans/implementations: fable-5, grok-4.5, or gpt-5.6-sol.
- Independence: prefer a different model than the implementer for adversarial review/verification — a model reviewing its own output is a weaker check. Default to cross-model (ideally cross-vendor); same-model review is fine for quick sanity passes, but escalate to a different model when the change is risky or the review really matters.
- Never use Haiku

### Mechanics
- Claude models (sonnet-5, opus-4.8, fable-5) run via the Agent/Workflow model parameter.
- Non-Claude models are only reachable via their own CLIs, headless, through Bash.
  - **grok-4.5** — default delegate for BOTH implementation and review. `grok -p`; JSON reply in `.text`. Prefer the `grok-review` / `grok-implementation` skills; raw:

    Review — grok ships a bundled `/review` skill that works headless. It takes mode flags and **no prompt**, collects the diff itself, and writes its notes to `$TMPDIR`. The repo-scoped denies are a seatbelt against grok helpfully editing something mid-review; leave the shell alone, `/review` needs it:
    ```bash
    grok --no-auto-update --cwd "$PWD" -m grok-4.5 --output-format json \
      --always-approve --sandbox read-only \
      --deny "Edit($PWD/**)" --deny "Write($PWD/**)" -p '/review --local'
    ```
    Modes: `--local` (uncommitted), `--branch <name>`, `--pr <number-or-url>` (posts a PENDING GitHub review for you to submit). This is the closest analogue to `codex review`.

    Review with a custom stance (`/review` accepts no prompt — name the target in `PROMPT.md` and let grok collect the diff itself):
    ```bash
    grok --no-auto-update --cwd "$PWD" -m grok-4.5 --output-format json --always-approve \
      --sandbox read-only --deny "Edit($PWD/**)" --deny "Write($PWD/**)" --prompt-file PROMPT.md
    ```
    Implement (autonomous edits, isolated with **plain git** — not grok's `-w`):
    ```bash
    REPO_ROOT="$(git rev-parse --show-toplevel)"
    WORKTREE_PARENT="$(mktemp -d "$(dirname "$REPO_ROOT")/grok-task.XXXXXX")"
    WORKTREE="$WORKTREE_PARENT/worktree"
    TASK_BRANCH="grok/$(basename "$WORKTREE_PARENT")"
    git -C "$REPO_ROOT" worktree add --detach "$WORKTREE"
    git -C "$WORKTREE" switch -c "$TASK_BRANCH"
    grok --no-auto-update --cwd "$WORKTREE" -m grok-4.5 --output-format json \
      --always-approve --prompt-file PROMPT.md
    # Require a commit SHA in the prompt; review and integrate it before cleanup:
    git -C "$REPO_ROOT" worktree remove "$WORKTREE"
    rmdir "$WORKTREE_PARENT"
    ```
    - `--prompt-file PATH` for long prompts (dodges shell quoting); `--json-schema '{...}'` for structured output.

    Verified traps (macOS; established on grok 0.2.118, `-w` / `--tools` / `/review` re-verified on 1.0.3 — re-check on a new major version):
    - **grok's `--sandbox read-only` is NOT codex's `-s read-only`.** Grok leaves `/tmp`, `/var/tmp`, `/var/folders` and `~/.grok` writable, so a repo under any of those is completely unprotected — while still logging `"enforced":true`. Codex's `-s read-only` blocks writes everywhere, including `/tmp`. Never conclude "the sandbox doesn't work" from a test in a temp dir; that mistake is what produced the previous version of this section.
    - **`-w`/`--worktree` is silently ignored in headless mode** (`-p` / `--prompt-file`): no worktree is created, edits land in the real checkout, and nothing is printed to stderr. Isolate with `git worktree add` and point grok at it via `--cwd`, the same way `codex-implementation` does.
    - **`--tools` / `--disallowed-tools` fail OPEN.** One unrecognized name anywhere in the list silently restores the *entire* toolset (exit 0, no warning). The README's own tool tables are wrong — it documents `bash` and `run_terminal_cmd`; the real tool is `run_terminal_command`, and subagents are `spawn_subagent`. Do not use either flag as a guard.
    - **`--deny` / `--allow` fail CLOSED and loudly** — an unknown prefix is a hard error with exit 1 and grok never starts. Prefer them. Prefixes: `Bash` `Edit` `Write` `Read` `Grep` `WebFetch` `MCPTool`. Scope review denies to the repo: a blanket `Write(**)` breaks `/review`'s own notes file, and denying `Bash` means hand-rolling diff materialization for no real gain — grok is cooperative, and a stray edit is visible in `git status` and revertible.
    - `--permission-mode plan` cancels repo/shell tool calls (`stopReason=cancelled` at turn 1–2 with a one-line preamble). It does *not* block grok's internal read of a large prompt file, and there is no ~100 KB input ceiling — 151 KB and 204 KB prompts were read in full.
    - Child-process network is **not** blocked on macOS under `read-only` (seccomp is Linux-only), so `gh`/`curl` inside a review work on macOS and may fail on Linux. Don't depend on it in either direction.

  - **codex (gpt-5.6 family)** — `codex exec`, model via `-m`: `gpt-5.6-sol` (frontier), `-terra` (balanced), `-luna` (fast/cheap); pin one explicitly. Default to `sol` unsupervised — `terra`/`luna` should be considered as always needing review from a more intelligent model. **Close stdin (`< /dev/null`, or `< prompt.txt` to pass the prompt)** or codex hangs on EOF (`Reading additional input from stdin...`) even with the prompt as an arg. Prefer the `codex-review` / `codex-implementation` / `codex-computer-use` skills; raw:

    ```bash
    codex exec -s read-only --skip-git-repo-check --json "SELF-CONTAINED PROMPT" < /dev/null
    ```

    `--json` → JSONL events (reply is the `item.completed` agent_message); `-o FILE` → last message to a file; `--output-schema FILE` → JSON-Schema-shaped reply; `-s workspace-write` to let it edit.
- Using grok/codex in subagents / workflows:
  - Spawn a thin Sonnet (low-effort) wrapper that only writes the prompt, runs the CLI, and relays the output verbatim — it must not do the task itself, or you're using the wrapper, not the target model.
  - Backgrounding a CLI run works only from the main session, never a subagent — a subagent's turn-end *is* its return, so backgrounding then yielding returns the wait and orphans the still-running CLI. Key it on runtime:
    - **≤10 min** → wrapper subagent runs the CLI in one **foreground** blocking Bash call, output to a file.
    - **might exceed 10 min** → not a subagent; background it from the **main session**, which persists across turns and gets the completion notification.
  - Label the subagent with the model slug (e.g. `grok-4.5:review-migration`) — it shows as Claude, so the label is the only signal of the real worker.
  - Describe any structured-output shape in prose (field names, not a literal `{"...":...}`) so it survives shell quoting.
  - Parallel implementers need worktree isolation so edits don't collide.
