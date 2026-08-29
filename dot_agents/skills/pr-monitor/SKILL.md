---
name: pr-monitor
description: >
  Monitor an existing pull request's current head for checks and review feedback until it is
  ready, blocked, merged, closed, or the monitoring window ends. Use when the user asks to
  watch, monitor, wait on, or babysit a PR. A monitoring request neither expands nor revokes
  authorization: continue already-authorized fixes, replies, and publication while keeping
  merging and deployment separate.
---

# PR monitor

Keep a pull request moving toward a terminal state while composing with the work and authorization
already established in the conversation.

## Preserve the active scope

Determine what the user has already authorized for this PR. Monitoring grants no new mutation
permission, but it does not reset an active implementation or publication task to read-only.

- If fixing and publishing this PR are already authorized, address verified feedback, validate the
  change, publish it, and continue monitoring the new head.
- If the active scope is review-only or monitoring began as a standalone request, report actionable
  findings without changing the PR.
- Reply to or resolve review threads only when that interaction is already authorized.
- Merging and deployment always remain separate actions unless the user explicitly included them.

Do not ask again for an action that remains within the established scope. Stop for authorization
only when a required action is genuinely outside it.

## Establish a checkpoint

Resolve the exact repository and PR, then record the current head commit, draft and mergeable
state, required checks, review state, and unresolved threads. Use conversation or task state for
the checkpoint; do not create a repository artifact unless requested.

Choose a finite monitoring horizon appropriate to the request. If the user supplied one, honor
it. Ask before extending it.

## Monitor changes

On each check:

- Reconfirm the PR and current head commit. If the head changed, discard head-specific conclusions
  and evaluate the new head.
- Consider only checks attached to the current head. Do not let stale successes or failures decide
  readiness.
- Inspect feedback newer than the checkpoint. Deduplicate repeated findings across reviewers,
  bots, checks, and existing threads.
- Verify automated findings against the source, then classify them as actionable, invalid, stale,
  or duplicate.
- Act on actionable findings within the active scope. If an update changes the head commit, reset
  head-specific conclusions and continue monitoring that new head.
- Update the checkpoint and stay quiet when nothing meaningful changed.

## Stop

Stop monitoring when:

- the current head is green and required feedback is resolved;
- the PR is merged or closed;
- a definitive blocker requires user input or authority outside the active scope; or
- the monitoring horizon ends.

Report the PR, current head commit, readiness or blocker, newly observed findings, relevant check
state, and any separate action still needed. Do not paste large logs or repeat unchanged status.
