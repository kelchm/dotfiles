{{- /*
How the scores are derived, so they can be redone. All of it is rough.

cost: what one benchmark task costs the user with each plan fully used, scaled linearly so that $0 is 10 and the most expensive model is 0.
  Task cost at API prices, at the top effort measured:
    DeepSWE v1.1 (2026-09-22): gpt-6-astra max $7.50.
    Artificial Analysis coding agent index (2026-10-03): claude-opus-5-5 max $13.04, claude-fable-5-1 max $12.39, gpt-6.1-sol xhigh $1.04.
  API-priced usage each plan gives per month when fully used, estimated on 2026-10-03 from the plans' weekly usage percentages against codeburn costs:
    Claude Max 5x ($100): about $5,200. ChatGPT Pro ($200): about $3,900.
  Grok is priced in Grok Build's own accounting, because its plan meter does not follow list API prices:
    `grok usage <session>` gives each session's cost. Token-only sessions fit $0.70 per million uncached input tokens, $0.16 cached, $3.00 output.
    32% of the week was used after $14.40 on that basis, so the SuperGrok base plan ($10) allows about $195 a month.
    A DeepSWE task at xhigh uses 0.26M uncached, 9.08M cached and 0.07M output tokens: $1.85, about 4% of a week.
    About $10 of that $14.40 was not token cost; sessions that searched X cost several times more per token.
  Cost per task: local GLM $0, gpt-6.1-sol $0.05, grok-4.6 $0.09, claude-fable-5-1 $0.24, claude-opus-5-5 $0.25, gpt-6-astra $0.39.
  The plan estimates are good to about a factor of two, so the three most expensive models are close to a tie.

intelligence: grok-4.6, gpt-6-astra and claude-fable-5-1 carry over from the September table. claude-opus-5-5 (66.0) and gpt-6.1-sol (62.9) are placed against gpt-6-astra (61.6) on the Artificial Analysis index, and the local GLM (63% on DeepSWE) against grok-4.6 (67%).

taste and notes: the owner's judgment.
*/ -}}
## Models

The user's read of each model as of 2026-10-03. Scores run from 0 to 10, and higher is always better. Cost is what a task costs the user on their plans: the cheapest model scores 10 and the most expensive 0. Intelligence is how hard a problem the model can handle unsupervised. Taste covers code quality, UI/UX, API design, and copy.

| provider      | model                      | cost | intelligence | taste | notes |
|---------------|----------------------------|------|--------------|-------|-------|
| `pi`          | `spark/GLM-5.3-Flash-EXL3` | 10   | 6            | 4     | Runs on the user's own hardware, so nothing it reads leaves the network. Takes security and reverse-engineering work that cloud models refuse. Slow on large tasks. |
| `codex`       | `gpt-6.1-sol`              | 9    | 8            | 5     | Strong reviewer; its code can be less tidy. |
| `grok`        | `grok-4.6`                 | 8    | 7            | 6     | The only one that can search X. |
| `claudeAgent` | `claude-fable-5-1`         | 4    | 9            | 9     |       |
| `claudeAgent` | `claude-opus-5-5`          | 4    | 9            | 9     | Strongest at UI design. |
| `codex`       | `gpt-6-astra`              | 0    | 8            | 6     |       |

- Pick the cheapest model whose intelligence and taste clear what the task needs. These are defaults, not limits: judge the output, not the price tag.
- When it is unclear whether a cheaper model clears the bar for something that ships, weigh intelligence first, then taste, then cost.
- Anything user-facing, including UI, API design, and copy, needs taste of at least 7.
