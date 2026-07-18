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
- When writing markdown, avoid the use of line breaks at a fixed column width

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
  - **grok-4.5** — default delegate for BOTH implementation and review. `grok -p`; JSON reply in `.text`. Edit-vs-read-only is set by `--permission-mode`, NOT `--sandbox` (that's a system FS/network boundary and does NOT stop grok editing the working dir — verified).

    Implement (autonomous edits):
    ```bash
    grok --no-auto-update -p "PROMPT" -m grok-4.5 --output-format json --always-approve
    ```
    Review (real read-only — `plan` blocks edits and overrides `--always-approve`):
    ```bash
    grok --no-auto-update -p "PROMPT" -m grok-4.5 --output-format json --permission-mode plan
    ```
    - `--prompt-file PATH` for long prompts (dodges shell quoting); `--json-schema '{...}'` for structured output; `-w`/`--worktree[=name]` for parallel-implementer isolation.

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
