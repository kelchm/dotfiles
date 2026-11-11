---
name: write-for-outside-readers
description: >
  Write issues, pull request descriptions, and commit messages that a maintainer outside the conversation can act on. Use when drafting for someone else's project or a public tracker, when asked to follow a project's template or contributing guide, or when a draft is called unclear, too heavy, or too terse. Not for review replies; whether and when to post is calibrate-initiative's call.
---

# Write for the outside reader

The reader is a maintainer who was not in the conversation. They cannot see its history or what the user already knows, and they decide from the first few lines whether this deserves their time. The draft is done when it stands on its own for that person.

## Match the project

Read the contributing guide, any agent guidance, and the issue or PR template, then a few recent merged PRs, commits, or comments near the change. Follow the template and the closest local style for length, headings, tone, and commit subjects. Where the project's conventions differ from the defaults here, the project wins.

## Say why it matters

Lead with what triggers the problem, what it costs, what changes, and how it was validated. Short is good; losing the reason is not. Keep the sentence a cold reader needs to care, for example that a cache which never expires keeps serving revoked credentials after rotation, not only that the TTL is missing.

Say which parts you observed, such as a reproduction, a log, or a failing test, and which you inferred from reading the source. A maintainer weighs them differently.

## Include what serves the reader

Detail is welcome when it helps the reader act. Several distinct problems may be better as several issues than as one long one.

Leave out conversation scaffolding ("as discussed", "per the user's request"), findings that do not affect this change or the reporter, private identifiers such as hardware addresses, hostnames, internal paths, or session IDs, and pasted source the reader can open themselves. Quoting the relevant lines, a log excerpt, or a version is fine when it supports the point. Metadata another skill requires, such as the `model-attribution` block, stays.
