{{- /*
How the scores are derived, so they can be redone. All of it is rough.

cost: a published benchmark's cost per task, scaled linearly so that $0 is 10 and the most expensive model is 0. No measurements of our own.
  Artificial Analysis coding agent index (2026-10-03), each model in its vendor's own harness:
    claude-opus-5-5 max $13.04, claude-fable-5-1 max $12.39, gpt-6-astra max $7.47, gpt-6.1-sol xhigh $1.04.
  DeepSWE v1.1 (2026-09-22), for the two models that index lacks:
    grok-4.6 xhigh $5.50. GLM-5.3-Flash is $0.48 hosted and $0 when run locally.
  The two sources agree where they overlap: gpt-6-astra at max is $7.50 on DeepSWE.
  These are API prices at each model's top measured effort. A lower effort costs less; high is roughly half of max.
  One published analysis of cost per task on subscriptions (aiandtractors.com/coding-agent-subscription-costs, 2026-10-01) puts gpt-6-astra below claude-fable-5-1 as well.

intelligence: grok-4.6, gpt-6-astra and claude-fable-5-1 carry over from the September table. claude-opus-5-5 (66.0) and gpt-6.1-sol (62.9) are placed against gpt-6-astra (61.6) on the Artificial Analysis index, and the local GLM (63% on DeepSWE) against grok-4.6 (67%).

taste and notes: the owner's judgment.
*/ -}}
## Models

The user's read of each model as of 2026-10-03. Scores run from 0 to 10, and higher is always better. Cost comes from a published benchmark's cost per task: the cheapest model scores 10 and the most expensive 0. Intelligence is how hard a problem the model can handle unsupervised. Taste covers code quality, UI/UX, API design, and copy.

| provider      | model                      | cost | intelligence | taste | notes |
|---------------|----------------------------|------|--------------|-------|-------|
| `pi`          | `spark/GLM-5.3-Flash-EXL3` | 10   | 6            | 4     | Runs on the user's own hardware, so nothing it reads leaves the network. Takes security and reverse-engineering work that cloud models refuse. Slow on large tasks. |
| `codex`       | `gpt-6.1-sol`              | 9    | 8            | 5     | Strong reviewer; its code can be less tidy. |
| `grok`        | `grok-4.6`                 | 6    | 7            | 6     | The only one that can search X. |
| `codex`       | `gpt-6-astra`              | 4    | 8            | 6     |       |
| `claudeAgent` | `claude-fable-5-1`         | 0    | 9            | 9     |       |
| `claudeAgent` | `claude-opus-5-5`          | 0    | 9            | 9     | Strongest at UI design. |

- Pick the cheapest model whose intelligence and taste clear what the task needs. These are defaults, not limits: judge the output, not the price tag.
- When it is unclear whether a cheaper model clears the bar for something that ships, weigh intelligence first, then taste, then cost.
- Anything user-facing, including UI, API design, and copy, needs taste of at least 7.
