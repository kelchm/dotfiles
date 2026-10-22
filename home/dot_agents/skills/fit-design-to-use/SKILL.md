---
name: fit-design-to-use
description: >
  Check a design against how it will actually be used before building or defending it. Use when choosing an approach, architecture, or tool; deciding whether to adopt something or build it; when a design keeps accumulating machinery; or when the user says it feels too complex or too thin, asks to step back, wants a middle ground, or says "prove it". Not for routine edits or clear, bounded tasks.
---

# Fit the design to the use

Designs drift when they start from a component or a threat model instead of from what the operator does. An example becomes a requirement, a personal sandbox picks up production gates, and passing tests or approving reviews get read as proof the shape was right. They show the code does what it was designed to do, not that the design fits.

Scale this to the decision. A small, reversible choice needs a sentence of reasoning, not research.

## Start from the use

Say plainly who uses this, how often, at what load, and what a failure would actually cost. Separate what the user asked for from what you inferred, and treat an example as an example unless the user says it is a requirement. When an inferred requirement drives the complexity, check the conversation and existing setup first, and ask only if the open choice would materially change the design.

Before designing a custom layer, check what the current setup and common tools already do. Search for the problem ("alert when a backup stops running") rather than the component you already picked ("an exporter that tracks per-volume state"). Read prior art as competition for your design, not as a scorecard for it.

## Compare on shared ground

When more than one shape is plausible, including the simplest one and the one already underway, walk each through the same few realistic scenarios: the normal path, the failures that actually happen, and recovery. A written walk-through usually settles it. Build a small probe only where a specific uncertainty could change the choice, and stop once what remains could not.

A shared comparison makes the choice better informed; it does not make it final. Revisit it when the use changes or a scenario turns out to be missing.

## Keep the guarantees that matter

Simpler means fewer moving parts for the same real job, not the fewest lines. Keep what real use depends on: stable identity, a way to recover, and anything holding data that could not be rebuilt. Drop protections for scenarios outside the agreed use or already ruled out, such as distributed locking for a job whose scheduler already guarantees a single process, and say what you dropped so the user can disagree.

The check cuts both ways. A baseline that defers something the use needs, such as completeness, correctness, or tests on the part that matters, is too thin, however small it is.
