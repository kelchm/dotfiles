---
name: test-the-claim
description: >
  Set up and report an experiment so its result supports the decision it is meant to inform. Use when designing or reading a benchmark, eval, A/B test, or model, prompt, or recipe comparison; when claiming a prototype proves a capability; or when asked "is this apples to apples?" or "doesn't that defeat the point?". Not for one-off smoke tests.
---

# Test the claim

Name the decision the experiment informs and the claim that would settle it, then ask what each condition can and cannot show. When building, do this before the harness, which otherwise tends to define the claim. When reading existing results, do it before drawing conclusions from them.

A run that supplies the relevant document tests reading and grounding, not finding it. Keep it as a labeled comparison if useful, but test retrieval with a condition that has to retrieve. A prototype that works on one input shows the path exists, not that it holds up.

Synthetic cases are good for isolating a behavior and are sometimes the only way to reach a rare one. Before generalizing to real use, check against representative cases: real messages, the actual documents, the recipe as it really runs. When a synthetic failure motivates a change, show it can happen with real inputs or say it has not been observed.

## Keep comparisons fair

Match the conditions that bear on the claim, such as inputs, prompts, settings, tool access, and serving setup, and disclose the differences that remain. Be clear whether you are comparing models or whole systems: when serving or harness differences could plausibly move the result, call it a system comparison or isolate the model.

Record what each run used, and isolate runs where an earlier run's artifacts, such as a transcript left in the working tree, could leak into a later one. Before discarding a run, check the run itself. An error in a shared log may belong to something else, and throwing away a valid run is as misleading as keeping an invalid one.

## Answer what sources can answer

When building an answer key or checking results, verify yourself whatever documents, code, or data can settle. Ask the user for judgment, preferences, or knowledge the sources lack, not for lookups.

## Report and stop

Report what was shown, what was not, and the next test that could change the decision. Stop widening the matrix once the decision is clear or further runs would not move it. The goal is an answer to this question, not an eval platform.
