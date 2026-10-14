{{- /*
How the scores are derived, so they can be redone. All of it is rough.

cost: a published benchmark's cost per task with every model at the same effort (high), scaled linearly so that $0 is 10 and the most expensive model is 0. No measurements of our own.
  DeepSWE v1.1 (2026-09-22), one harness for every model, at high effort:
    claude-fable-5 $9.18, claude-opus-5 $6.08, grok-4.6 $4.38, gpt-6-astra $3.92. GLM-5.3-Flash is $0.48 hosted (max) and $0 when run locally.
  DeepSWE has not run claude-fable-5-1 or claude-opus-5-5 yet, so the previous point releases stand in for them.
  gpt-6.1-sol is not on DeepSWE either; its figure is the Artificial Analysis coding agent index at high effort (2026-10-03): $0.89.
  Why a common effort: at max effort that index puts claude-opus-5-5 ($13.04) level with claude-fable-5-1 ($12.39), because Opus takes four times as many steps (155 against 37) while Fable's tokens list at 2.5 times the price. At equal effort Fable costs more.

intelligence: grok-4.6, gpt-6-astra and claude-fable-5-1 carry over from the September table. claude-opus-5-5 (66.0) and gpt-6.1-sol (62.9) are placed against gpt-6-astra (61.6) on the Artificial Analysis index, and the local GLM (63% on DeepSWE) against grok-4.6 (67%).

taste and notes: the owner's judgment.
*/ -}}
## Models

The user's read of each model as of 2026-10-03. Scores run from 0 to 10, and higher is always better. Cost comes from a published benchmark's cost per task at equal effort: the cheapest model scores 10 and the most expensive 0. Intelligence is how hard a problem the model can handle unsupervised. Taste covers code quality, UI/UX, API design, and copy.

| provider      | model                      | cost | intelligence | taste | notes |
|---------------|----------------------------|------|--------------|-------|-------|
| `pi`          | `spark/GLM-5.3-Flash-EXL3` | 10   | 6            | 4     | Runs on the user's own hardware, so nothing it reads leaves the network. Takes security and reverse-engineering work that cloud models refuse. Slow on large tasks. |
| `codex`       | `gpt-6.1-sol`              | 9    | 8            | 5     | Strong reviewer; its code can be less tidy. |
| `codex`       | `gpt-6-astra`              | 6    | 8            | 6     |       |
| `grok`        | `grok-4.6`                 | 5    | 7            | 6     | The only one that can search X. |
| `claudeAgent` | `claude-opus-5-5`          | 3    | 9            | 9     | Strongest at UI design. |
| `claudeAgent` | `claude-fable-5-1`         | 0    | 9            | 9     |       |

- Pick the cheapest model whose intelligence and taste clear what the task needs. These are defaults, not limits: judge the output, not the price tag.
- When it is unclear whether a cheaper model clears the bar for something that ships, weigh intelligence first, then taste, then cost.
- Anything user-facing, including UI, API design, and copy, needs taste of at least 7.
