---
name: pr-monitor
description: >
  Monitor an existing pull request's current head for checks and review feedback until it is
  ready, blocked, merged, closed, or the monitoring window ends. Use when the user asks to
  watch, monitor, wait on, or babysit a PR. Monitoring preserves the active work context while
  keeping merge and deployment separate.
---

# PR monitor

Keep a pull request moving toward a terminal state while composing with the work and authorization
already established in the conversation.

## Preserve the active work

Monitoring grants no new mutation permission, but it does not reset an active implementation or
publication task to read-only.

Continue already-agreed implementation and publication through verified fixes and the resulting
new head. If monitoring began as a standalone or review-only request, report findings without
silently expanding the task. Use `calibrate-initiative` when the appropriate degree of follow-through
depends on repository or contribution context, and `review-feedback` to evaluate new comments.

Do not ask again for an action that remains within the established scope. Replying publicly,
merging, and deployment remain separate when they were not already part of that scope.

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
  bots, checks, and existing threads, then form a verdict with `review-feedback`.
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
