---
name: pr-monitor
description: >
  Monitor an existing pull request's current head for checks and review feedback until it is
  ready, blocked, merged, closed, or the monitoring window ends. Use when the user asks to
  watch, monitor, wait on, or babysit a PR. Monitoring is read-only; fixes, replies, pushes,
  merging, deployment, and rollout verification are separate actions.
---

# PR monitor

Watch a pull request for meaningful changes without turning monitoring into ownership of its
entire lifecycle.

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
- Verify automated findings against the source before calling them blockers.
- Update the checkpoint and stay quiet when nothing meaningful changed.

Monitoring permission is read-only. If a new finding needs a code change, reply, push, merge, or
deployment action, report it or perform it only when that separate action is already authorized.

## Stop

Stop monitoring when:

- the current head is green and required feedback is resolved;
- the PR is merged or closed;
- a definitive blocker requires user input or separately authorized work; or
- the monitoring horizon ends.

Report the PR, current head commit, readiness or blocker, newly observed findings, relevant check
state, and any separate action still needed. Do not paste large logs or repeat unchanged status.
