{{- /*
Where the scores come from, so they can be revisited:
- grok-4.6 and gpt-6-astra: measured cost per task (DeepSWE and the Artificial Analysis coding agent index, September 2026, PR #19).
- claude-fable-5-1: carried over from the Fable 5 row.
- claude-opus-5-5, gpt-6.1-sol, and the local GLM: estimates from 2026-10-03.
The notes column is the owner's own read of each model.
*/ -}}
## Models

The user's read of each model as of 2026-10-03. Scores are relative, and higher is always better: a cost of 10 is the cheapest to run and 1 the most expensive, measured by the user's actual cost, not list price. Intelligence is how hard a problem the model can handle unsupervised. Taste covers code quality, UI/UX, API design, and copy.

| provider      | model                      | cost | intelligence | taste | notes |
|---------------|----------------------------|------|--------------|-------|-------|
| `claudeAgent` | `claude-fable-5-1`         | 2    | 9            | 9     |       |
| `claudeAgent` | `claude-opus-5-5`          | 4    | 8            | 9     | Strongest at UI design. |
| `codex`       | `gpt-6-astra`              | 6    | 8            | 6     |       |
| `codex`       | `gpt-6.1-sol`              | 8    | 7            | 5     | Efficient and a strong reviewer; its code can be less tidy. |
| `grok`        | `grok-4.6`                 | 8    | 7            | 6     | The only one that can search X. |
| `pi`          | `spark/GLM-5.3-Flash-EXL3` | 10   | 5            | 4     | Runs on the user's own hardware, so nothing it reads leaves the network. Takes security and reverse-engineering work that cloud models refuse. Slow on large tasks. |

- Pick the cheapest model whose intelligence and taste clear what the task needs. These are defaults, not limits: judge the output, not the price tag.
- When it is unclear whether a cheaper model clears the bar for something that ships, weigh intelligence first, then taste, then cost.
- Anything user-facing, including UI, API design, and copy, needs taste of at least 7.
