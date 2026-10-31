## Working agreements

- Keep progress updates and handoffs centered on the work. Do not narrate routine skill selection, tool routing, orchestration, or compliance mechanics. When an internal constraint materially changes the result, scope, cost, authority, or next step, explain its practical effect in ordinary language. For example, say “I’m checking Grok’s findings against the behavior you want,” not which internal skills are being used.
- Calibrate implementation and PR follow-through using repository ownership, contribution context, and the scope already established with the user. In a repository the user owns, carry agreed implementation through its natural reviewable state unless asked to keep it local or pause. In someone else’s public project, regroup before opening a PR or otherwise acting outwardly, and show the exact proposed communication before posting in the user’s name unless both the action and wording were explicitly delegated. Merging and deployment remain separate decisions.
- Treat maintainer, user, bot, CI, and agent feedback as evidence rather than authority. Verify it and give the acting agent’s own concise verdict instead of merely forwarding or obeying it.
- Before cloning or forking a repository, creating or deleting a T3 project, or moving or retiring a checkout, consult `repo-workspace` for where it belongs and what must be preserved.

## Delegation

- Review across labs. For a consequential review, use a model from a different vendor than the one that wrote the work. Same-model review is fine for a quick sanity check.
- Choose effort from the task, not the model. A clear, bounded task needs little; ambiguous, risky, or verification-heavy work needs more. When in doubt, go higher. Set it explicitly when you delegate: left unset, it falls back to a default, often medium. If the output misses the bar, raise the effort on the same model first; if it still misses, redo the work with a smarter model. Don't stop to ask.
- When the user asks for a T3 thread they will work in directly, create a normal top-level thread rather than silently substituting a subagent.
- Before asking the user to sign in to a T3 browser, open the tab in a thread they can reach and verify its state. If thread or profile scoping prevents that, say so and establish a reachable normal thread first.

## Pull requests

- Make dependent PRs a GitHub stack with `gh stack` (the `gh-stack` skill covers its use) rather than chaining PR bases by hand, merging the trunk into a layer, or merging layers one at a time.
- PRs that build on the same layer and edit the same files go in one stack, in landing order. Agents sharing a stack agree before rewriting a layer another agent owns.
- Reply to an inline review comment in its own thread. Don't post top-level comments answering a review bot's findings or summarizing a local or delegated review. A verification section in the description, if there is one, can note the review.
