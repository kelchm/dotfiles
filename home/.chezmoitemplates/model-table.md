{{- /*
How the scores are derived, so they can be redone. All of it is rough.

cost: Artificial Analysis Coding Agent Index v2.1 pay-per-token API cost per task (2026-11-21), scaled linearly so $0 is 10 and the most expensive row (claude-fable-5-2 xhigh, $15.47) is 0. No measurements of our own.
  Coding Agent Index v2.1 (native harness):
    spark/GLM-5.3-Flash $0 local ($0.58 hosted on Intel v5) -> 10; gpt-6.2-sol $0.90 (xhigh) / $1.22 (max) -> 9; gpt-6.2-astra $3.20 (xhigh) / $5.12 (max) -> 7; opencode-go/glm-5.3 $5.41 (max) -> 6; gemini-4-neon $6.86 (xhigh) -> 6; claude-opus-5-5 $12.61 (max) -> 2; claude-fable-5-2 $15.47 (xhigh) -> 0.
  grok-4.6 is not on Coding Agent Index v2.1; it carries over at 5 from DeepSWE v1.1 high ($4.38). grok-4.7 is $15.35 on CAI v2.1 (0) for index 42, so the table stays on grok-4.6.
  Effort notes: claude-fable-5-2 hits the same CAI score (58) at high ($7.51, ~5) as xhigh ($15.47), while max ($44.22, score 56) hits timeouts. gpt-6.2-astra xhigh ($3.20) ties max ($5.12) at 53. OpenCode announced a 60% pay-per-token cut on GLM-5.3 on 2026-11-21 (separate from Go caps), not yet reflected in AA's bill.

intelligence: anchored to Artificial Analysis Intelligence Index v5 and Coding Agent Index v2.1 (2026-11-21):
  claude-fable-5-2 (#1 Intelligence Index, 58 CAI) -> 10.
  gemini-4-neon (61 Intel, 59 CAI #1), claude-opus-5-5 (59 Intel, 58 CAI), and gpt-6.2-astra (62 Intel #2, 53 CAI) -> 9.
  gpt-6.2-sol (57 Intel, 49-50 CAI, FrontierCode 42) -> 8.
  opencode-go/glm-5.3 (32 Intel, 40 CAI, 66.9% DeepSWE) and grok-4.6 (31 Intel, 67% DeepSWE) -> 5.
  spark/GLM-5.3-Flash (28 Intel, 63% DeepSWE) -> 4.

taste, rapport, and notes: the owner's judgment informed by Arena WebDev/Agent Chat and practitioner reports.
*/ -}}
## Models

The user's read of each model as of 2026-11-21. Scores run from 0 to 10, and higher is always better. Cost comes from a published coding-agent benchmark's cost per task, scaled linearly from $0 (10) to the most expensive model (0). Intelligence is how hard a problem the model can handle unsupervised. Taste covers code quality, UI/UX, API design, and copy. Rapport is how pleasant and low-friction the model is to talk to: reading intent, staying natural and concise, taking steering well, and pushing back honestly without lecturing or asking tedious questions.

| provider      | model                 | cost | intelligence | taste | rapport | notes |
|---------------|-----------------------|------|--------------|-------|---------|-------|
| `pi`          | `spark/GLM-5.3-Flash` | 10   | 4            | 4     | 5       | Runs locally on the home-lab Sparks so nothing it reads leaves the network; unlimited and won't refuse security/RE work. Use this explicit model ID rather than `pi`'s `default` alias. Slow on large tasks. |
| `codex`       | `gpt-6.2-sol`         | 9    | 8            | 5     | 4       | Strong, cheap reviewer; FrontierCode matches Astra, though repo Q&A dropped vs 6.1 and code can be less tidy. Rigid in chat. Hard `cyberPolicy` blocks on firmware/RE. |
| `codex`       | `gpt-6.2-astra`       | 7    | 9            | 6     | 4       | Fast, token-efficient worker for well-scoped or headless tasks (`xhigh` ties `max` on coding at $3.20 vs $5.12; #2 general intelligence, behind Neon/Claude on coding index). Rigid intent reading, admits uncertainty less often, and hard `cyberPolicy` blocks on RE. |
| `opencode`    | `opencode-go/glm-5.3` | 6    | 5            | 5     | 6       | Hosted full GLM; trails frontier on general coding and runs slow, but punches well above its tier on security, auditing, RE, and repo Q&A without cloud-filter refusals. Subject to OpenCode Go weekly caps. |
| `antigravity` | `gemini-4-neon`       | 6    | 9            | 7     | 9       | #1 on Coding Agent Index (59 at `xhigh`), neck-and-neck with Opus on everyday dev work, and standout at natural copy and easy-to-steer conversation; zero observed RE refusals so far (unverified on heavy cyber). Weaker than Claude on visual UI/3D and vision. Taste is provisional while building familiarity. |
| `grok`        | `grok-4.6`            | 5    | 5            | 6     | 6       | The only one that can search X. Blunt, plain-English reviewer; occasional jargon quirks. Avoid `grok-4.7` for coding ($15.35/task on CAI for index 42). |
| `claudeAgent` | `claude-opus-5-5`     | 2    | 9            | 9     | 8       | Thorough, pragmatic workhorse for verifiable, detail-heavy, or high-risk work (migrations, repros, audits); turns over every stone and has >4× the Claude sub headroom of Fable, but can over-check, bloat specs, or spin on minor feedback. Can silently downgrade cyber/RE turns to Opus 4.8. |
| `claudeAgent` | `claude-fable-5-2`    | 0    | 10           | 9     | 7       | Strongest intelligence, creative UI/WebDev, and engineering judgment—best for unprovable/open-ended design, challenging a bad premise, or breaking an Opus loop when work is ready to ship. Slightly looser on small details and test harnesses than Opus; burns Claude sub limits >4× faster. Prefer `high` (same CAI 58 as `xhigh` at half the cost). Can silently downgrade/block cyber turns. |

- Pick the cheapest model whose intelligence and taste clear what the task needs. These are defaults, not limits: judge the output, not the price tag.
- Keep fast mode off by default. Use it only when the task truly requires lower latency or the user explicitly instructs you to use it.
- Treat `high` (or `xhigh` for deep audits) as the practical effort ceiling on Claude and Codex; avoid `max` unless explicitly requested, since current models overthink and often score worse at `max` while multiplying cost. Past `high`, weigh stepping up a model at `high` (e.g., `claude-fable-5-2` at `high`) instead of pushing a cheaper model to `max`.
- When it is unclear whether a cheaper model clears the bar for something that ships, weigh intelligence first, then taste, then cost.
- Anything user-facing, including UI, API design, and copy, needs taste of at least 7.
- Weigh rapport for interactive threads (planning, brainstorming, debugging together); headless delegated tasks can ignore it.
- Between Claude models, default to `claude-opus-5-5` for verifiable, detail-heavy work (repros, audits, large migrations); reach for `claude-fable-5-2` for unprovable judgment calls, creative UI, non-obvious options, or unsticking a thread spinning on nitpicks.
- For firmware, reverse engineering, binary patching, or security execution, default to `opencode-go/glm-5.3` (or `pi` `spark/GLM-5.3-Flash` when data must stay local or runs are unbounded, and `gemini-4-neon` for bounded work, noting heavy cyber is unverified). OpenAI Codex trips hard mid-run `cyberPolicy` blocks on disassembly/RE and security-flavored phrasing, and Anthropic can silently downgrade cyber turns to Opus 4.8 or hard-block live firmware/security sessions.
