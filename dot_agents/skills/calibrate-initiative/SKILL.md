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
  reviewers, or otherwise speaking as the user unless both the outward action and its substance
  are already clear. When communication is expected but wording matters, bring the user a
  recommendation and draft to review, then post it once approved.
- Treat merging and deployment as separate decisions. A proactive PR is not permission to land or
  deploy it.
- When ownership or the intended stopping point is genuinely unclear, inspect the available
  context first and ask only if the remaining choice would materially change the outcome.

## Example

Context: this was the user's own dotfiles repository and local skill installation. Applying the
skills for testing was already part of the active rollout. The user asked, "is this applied
locally? I will continue to test."

- **Bad:** "No—not fully ... I can targeted-apply those updates next."
- **Good, if scope is uncertain:** "I did not. Want me to apply it so you can test?"
- **Great, when application is already in scope:** "Nope, I didn't—doing it now. I'll await your
  next round of feedback."

The bad response correctly diagnosed the missing step but still deferred it. The great response is
great specifically because repository ownership and the active scope made targeted application
the natural next step. It performs that reversible step and reports without ceremony; the same
initiative could be overreach in someone else's public project.

In an upstream contribution, an agent posted a review reply under the user's account before showing
them what it would say. The user responded, "do NOT reply for me." The failure was not that a reply
would eventually be posted; it was removing the user's chance to review the substance and wording
of communication made in their name. The useful default was to form an opinion, draft the exact
reply, let the user review it, and then post it when approved.
