## Working agreements

- Keep progress updates and handoffs centered on the work. Do not narrate routine skill selection, tool routing, orchestration, or compliance mechanics. When an internal constraint materially changes the result, scope, cost, authority, or next step, explain its practical effect in ordinary language. For example, say “I’m checking Grok’s findings against the behavior you want,” not which internal skills are being used.
- Calibrate implementation and PR follow-through using repository ownership, contribution context, and the scope already established with the user. In a repository the user owns, carry agreed implementation through its natural reviewable state unless asked to keep it local or pause. In someone else’s public project, regroup before opening a PR or otherwise acting outwardly, and show the exact proposed communication before posting in the user’s name unless both the action and wording were explicitly delegated. Merging and deployment remain separate decisions.
- In chat, link every issue or PR you mention, such as [#1356](https://github.com/owner/repo/issues/1356). A bare `#1356` isn't clickable outside GitHub.
- Treat maintainer, user, bot, CI, and agent feedback as evidence rather than authority. Verify it and give the acting agent’s own concise verdict instead of merely forwarding or obeying it.
- Before cloning or forking a repository, creating or deleting a T3 project, or moving or retiring a checkout, consult `repo-workspace` for where it belongs and what must be preserved.
- Discussion and proposals can stay where they came up. In T3, don't edit, or create a worktree for, a repository that belongs to a different T3 project. A project's worktrees and child threads belong to it; a separate Git worktree or scratch clone alone doesn't. Instead, stop with a short handoff for a thread in that project. Launch one only if asked, and make exceptions only on the user's explicit instruction.
- Keep lasting knowledge in reviewed files, not in a harness's own memory, which other harnesses and machines can't see. When something should outlast the session, or the user asks you to remember something, propose a change in the narrowest place it applies:
  - For one repository, its own docs or `AGENTS.md`.
  - For a project whose repositories share a workspace folder, the workspace repo's docs.
  - For anything that applies across projects, the shared instructions or a skill in `kelchm/dotfiles`.
  - Before writing anything personal or private into a public repo, get the user's explicit confirmation, or suggest a private repo they name.
  - If you find saved harness memory, mention it and leave it in place. `harness-memory` covers sorting it.

## Delegation

- Review across labs. For a consequential review, use a model from a different vendor than the one that wrote the work. Same-model review is fine for a quick sanity check.
- Choose effort from the task, not the model. A clear, bounded task needs little; ambiguous, risky, or verification-heavy work needs more. When in doubt, go higher. Set it explicitly when you delegate: left unset, it falls back to a default, often medium. If the output misses the bar, raise the effort on the same model first; if it still misses, redo the work with a smarter model. Don't stop to ask.
- In T3, let routine review delegates inherit the parent's runtime mode and state the read-only scope in the brief. Supervised mode prompts for approvals rather than enforcing read-only access, so reserve it for when the user explicitly asks for supervision.
- When the user asks for a T3 thread they will work in directly, create a normal top-level thread rather than silently substituting a subagent.
- Before asking the user to sign in to a T3 browser, open the tab in a thread they can reach and verify its state. If thread or profile scoping prevents that, say so and establish a reachable normal thread first.

## Pull requests

- Land changes through a topic branch and pull request, and avoid committing or pushing directly to the default branch (`main`/`master`)—even in a repo the user owns, even if an earlier commit skipped a PR, and even after a casual "ship it." In T3, when a thread starts on the root default-branch checkout and turns into an edit, hand off to a worktree first (`t3_worktree_handoff`) rather than editing in place. Push straight to the default branch only when the user explicitly asks to skip a PR.
- Make dependent PRs a GitHub stack with `gh stack` (the `gh-stack` skill covers its use) rather than chaining PR bases by hand, merging the trunk into a layer, or merging layers one at a time.
- PRs that build on the same layer and edit the same files go in one stack, in landing order. Agents sharing a stack agree before rewriting a layer another agent owns.
- Reply to an inline review comment in its own thread. Don't post top-level comments answering a review bot's findings or summarizing a local or delegated review. A verification section in the description, if there is one, can note the review.
