## Picking models for workflows and subagents

Rankings are relative; higher is better. Cost reflects the user's actual cost rather than list price. Intelligence is how hard a problem the model can handle unsupervised. Taste covers code quality, UI/UX, API design, and copy. `start` is the effort to use first; raise effort before switching models.

| model       | start  | cost | intelligence | taste |
|-------------|--------|------|--------------|-------|
| grok-4.6    | medium | 8    | 7            | 6     |
| gpt-6-astra | xhigh  | 6    | 8            | 6     |

### Model-selection guidance

- These are defaults, not limits. If a cheaper model's output misses the bar, rerun or redo the work with a smarter model without asking. Judge the output, not the price tag.
- Cost is a tie-breaker only; when axes conflict for anything that ships, intelligence > taste > cost.
- Grok-4.6 is the default for clear-spec implementation, migrations, mechanical refactors, and bulk analysis. Fall back to gpt-6-astra when Grok is not a fit.
- User-facing work, including UI, API design, and copy, stays in the current session. Nothing on this menu scores taste 7 or above.
- Prefer gpt-6-astra or grok-4.6 for reviews of plans and implementations, using a different vendor than the implementer when the review is consequential. Same-model review is fine for quick sanity checks.

### Delegation routes

- Grok and Codex models run through their headless CLIs. Use the matching review, implementation, or computer-use skill; those skills own the exact invocation, execution placement, sandbox, worktree, prompt, reporting, and recovery mechanics. Do not duplicate or improvise those contracts here.
