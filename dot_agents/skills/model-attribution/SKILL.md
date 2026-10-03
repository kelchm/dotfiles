---
name: model-attribution
description: >
  Record which model wrote an issue, comment, pull request, or commit. Use before creating or editing any of these on the user's behalf (`gh issue create`, `gh pr create`, a review or issue comment, `git commit`), and for "attribution", "footer", or "co-author" requests.
---

# Model attribution

Record the model that wrote an artifact so it can be traced back later.

**The project decides.** If the repository's `AGENTS.md`, `CLAUDE.md`, or `CONTRIBUTING.md` says anything about AI attribution, do what it says and nothing below. If it says nothing, attribute only in repositories the user owns that are not forks. Add nothing in anyone else's project.

**Issues, comments, and pull request descriptions.** End the body with this hidden block, and nothing after it:

```
<!-- attribution
model: MODEL_ID
harness: HARNESS
thread: T3_THREAD_ID
-->
```

`MODEL_ID` is the exact ID the runtime uses, not a display name. `HARNESS` is the CLI you are running in. In T3 Code, `t3_thread_configuration` returns the model ID and the thread ID. Leave out a line you can't fill; never guess one.

The block names whoever wrote that text. A pull request description and its commits can have different authors.

**Commits.** End the message with one trailer for the model that wrote the change. When you commit a delegate's work, that is the delegate:

```
Co-Authored-By: MODEL_ID <noreply@VENDOR_DOMAIN>
```

`VENDOR_DOMAIN` is the model vendor's domain. If your harness already adds a co-author trailer for you, that one is enough; don't add a second.

No emoji, no links, no "Generated with" line. Don't attribute text the user wrote. Skip all of this when the user says to.
