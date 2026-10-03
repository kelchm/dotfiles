## Picking models for delegated work

Scores are relative; higher is better. Cost reflects the user's actual cost rather than list price. Intelligence is how hard a problem the model can handle unsupervised. Taste covers code quality, UI/UX, API design, and copy.

| provider      | model                      | cost | intelligence | taste |
|---------------|----------------------------|------|--------------|-------|
| `claudeAgent` | `claude-fable-5-1`         | 2    | 9            | 9     |
| `claudeAgent` | `claude-opus-5-5`          | 4    | 8            | 9     |
| `codex`       | `gpt-6-astra`              | 6    | 8            | 6     |
| `codex`       | `gpt-6.1-sol`              | 8    | 7            | 5     |
| `grok`        | `grok-4.6`                 | 8    | 7            | 6     |
| `opencode`    | `spark/GLM-5.3-Flash-EXL3` | 10   | 5            | 4     |

- Pick the cheapest model whose intelligence and taste clear what the task needs. These are defaults, not limits. If the output misses the bar, raise the effort, then redo the work with a smarter model, without asking. Judge the output, not the price tag.
- Cost is a tie-breaker only; when axes conflict for anything that ships, intelligence > taste > cost.
- Anything user-facing, including UI, API design, and copy, needs taste of at least 7.
- For a consequential review, use a different vendor than the implementer. Same-model review is fine for quick sanity checks.
- Two things the scores don't show: only Grok can search X, and `spark/GLM-5.3-Flash-EXL3` runs on this machine, so nothing it reads leaves it, but it is slow and handles one task at a time.

