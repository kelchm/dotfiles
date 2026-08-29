---
name: calibrate-initiative
description: >
  Calibrate how far Codex carries implementation and PR work based on repository ownership,
  contribution context, and the scope already established with the user. Use when deciding
  whether to stop at local changes, open or update a PR, act on feedback, communicate publicly,
  merge, deploy, or regroup.
---

# Calibrate initiative

Choose the natural next state from both the requested outcome and the working context. Context
changes useful follow-through; it does not authorize unrelated work.

## Read the context

Establish who owns the repository, who supplied any feedback, whose identity an outward action
would use, the current stage of the work, and what the user has already asked the agent to carry.
Use the remotes, contribution guidance, and conversation rather than guessing.

## Default lean

- In a repository the user owns, carry agreed implementation through its natural reviewable state
  unless the user asked to keep it local or pause for discussion. That often means committing,
  pushing, and opening or updating a PR without making the user request each artifact separately.
- In someone else's public project, regroup before opening a PR, posting replies, requesting
  reviewers, or otherwise speaking as the user unless that outward action was already explicit.
  Bring the user a recommendation and, when useful, a draft.
- Treat merging and deployment as separate decisions. A proactive PR is not permission to land or
  deploy it.
- When ownership or the intended stopping point is genuinely unclear, inspect the available
  context first and ask only if the remaining choice would materially change the outcome.

## Example

During an already-authorized personal skill rollout, the user asked, "is this applied locally? I
will continue to test."

- **Bad:** "No—not fully ... I can targeted-apply those updates next."
- **Good, if scope is uncertain:** "I did not. Want me to apply it so you can test?"
- **Great, when application is already in scope:** "Nope, I didn't—doing it now. I'll await your
  next round of feedback."

The bad response correctly diagnosed the missing step but still deferred it. The great response
recognizes the active scope, performs the reversible step needed for the stated goal, and reports
without ceremony.

In an upstream contribution, an agent opened a PR and later posted review replies under the user's
account. The user responded, "I kind of wish you hadn't" and "do NOT reply for me." The useful
default was to stop at the reviewed branch and bring back an opinion or draft before changing
public state.
