---
name: t3-delegate
description: >
  Delegate work to other models through T3 Code and get reliable results back. Use before handing off an implementation, review, or research task inside T3 Code ("have Sol do it", "get a second opinion", "run these in parallel"), and when collecting the results.
---

# Delegating in T3 Code

T3 runs the mechanics. Four things are left to you.

**Shape.** A `delegate_task` child works in your checkout, so run one writer at a time. Reviewers and researchers can run in parallel. Writing that must run in parallel, or any work that must stay out of your checkout, gets its own thread: `t3_thread_launch` with a `worktree` workspace, told to `t3_thread_send` you its report when done. Launch one when the user asked for parallel or isolated work; otherwise ask first.

**Model and effort.** Pick the model from the Models table in your instructions and the effort from the task. Set both in the call: an unset model means yours, and an unset effort usually means medium.

**Brief.** The child sees only your prompt. Give it the goal, the exact files or commit, and what done looks like. End with:

> - Work only in this checkout. Don't create branches or worktrees. Scratch files go in `/tmp`.
> - Don't ask questions; state your assumptions in the report.
> - Don't delegate, and don't commit.
> - Make your final message the complete report.

Tell a reviewer not to edit files.

**Result.** Treat the report as a claim: check the diff or reproduce the finding before you act on it, then commit yourself.
