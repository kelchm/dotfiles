## Models and delegation

- Do the work in the current session by default. Delegate when it buys independent checking, useful parallelism, or isolation of a bounded task's context. Keep interactive design and scope decisions with the acting agent.
- When choosing a new implementation delegate, prefer Claude Opus 5.5 at medium effort. This is a preference, not a requirement to hand off work or replace the active model. Codex/Astra and Grok remain alternatives when the task, availability, or observed results favor them.
- Use an independent review for consequential changes. Prefer a different vendor when practical; a quick sanity check can use the same model. Scale effort to the risk, verify findings yourself, and re-review fixes only when unresolved risk warrants it. Do not create an automatic review/fix loop.
- Choose model and effort explicitly for each delegate. Raise effort or change approach when needed; do not repeatedly retry an unsuitable model. If the problem is missing context or unclear scope, fix that first.
- Optimize for accepted results and human correction time. Included subscription quota matters more here than API list prices. Available plans: Claude 5x, ChatGPT/Codex base Pro 5x, Grok Base, and OpenCode Go $10. Go is optional capacity for bounded work, not a mandatory cheap-worker stage. Do not assume paid Zen overflow is authorized.
- Keep model choice discretionary within these preferences. Report which CLI, model, and effort actually ran, including any fallback; do not add automatic cross-provider retry chains.

### CLI routes

Use `delegate-claude`, `delegate-codex`, or `delegate-grok` for CLI implementation and review. Each skill owns its CLI's invocation and guards; use native subagents when they already provide the needed model and isolation. Current candidates are `claude-opus-5-5`, `gpt-6-astra`, and `grok-4.6`; confirm availability rather than treating this list as an exhaustive ranking. OpenCode Go uses the configured OpenCode workflow; no CLI delegation contract for it is established here.
