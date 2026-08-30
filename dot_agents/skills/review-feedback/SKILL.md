---
name: review-feedback
description: >
  Evaluate feedback from maintainers, users, review bots, CI, or other agents and give the acting
  agent's own verdict. Use when triaging review comments, deciding whether findings are valid,
  stale, overstated, or out of scope, or choosing what to fix, reject, discuss, or verify next.
---

# Review feedback

Treat feedback as evidence, not authority. The acting agent owns the disposition.

## Form a view

Check the finding against the current head and the relevant source, runtime evidence, tests, or
project policy. Consider separately whether the claim is true, important, current, in scope, and
supported by the proposed fix. State a concise verdict and why; do not merely relay the reviewer.

## Respond proportionally

Give the verdict first. A request to assess or triage feedback is not by itself a request to change
code or publish a response. Act on a finding only when the current request or an already-established
implementation task includes doing so.

- When the feedback exposes an obvious miss, say so plainly and fix it when doing so is within that
  active implementation scope.
- When the concern is real but its severity or prescription is inflated, address the narrow issue
  without inheriting the reviewer's scope.
- When the claim is wrong or stale, explain the evidence and leave the code alone.
- When a flawed finding contains a legitimate underlying risk, reject the claim narrowly while
  preserving that risk as a separate decision.
- When evidence is ambiguous or consequences are material, discuss it with the user or seek an
  independent review. Model agreement is not proof; the acting agent still synthesizes the result.

Compose with `calibrate-initiative` when acting on feedback would publish changes or communicate in
the user's name.

## Example

CodeRabbit found that a `> 0` guard hid volumes that had never completed a backup. The agent's
verdict was: "it's valid ... I traded a false positive for a false negative without noticing," and
it proposed a focused rule.

Later, CodeRabbit inferred the wrong PVC name from a convention. The agent checked the live PVC,
claim reference, and metric, rejected the claim, but retained one valid sub-point: the exemption
should include the namespace. One review was accepted, one was disproved, and neither disposition
came from the bot's confidence or severity label.
