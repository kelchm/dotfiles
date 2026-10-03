---
name: t3-delegate
description: >
  Hand work to other agents and models through T3 Code's orchestrator, and get reliable results back. Use whenever you are about to delegate inside T3 Code: an implementation, a code review, research, a second opinion, or several tasks in parallel, including casual asks like "have Sol do it", "get GLM to review this", or "run these in parallel". Also use while waiting on, steering, or collecting results from delegated work. Covers how to shape the work, what every brief must say, and the known T3 gaps that make delegated work fail quietly.
---

# Delegating in T3 Code

T3 handles the mechanics: it starts the child, tracks it, and wakes you when it finishes. This skill covers what T3 leaves to you: choosing the shape of the work, writing a brief the child can act on alone, and checking what comes back. Pick the model from the model table in your global instructions. Tool names below are bare; your harness may prefix them (for example `mcp__t3-code__delegate_task`).

## 1. Choose the shape

A child started with `delegate_task` works in your checkout, on your branch. That suits the usual loop, where one child implements, you read the diff, and other children review it. It is also the main hazard, because two writers in one checkout overwrite each other.

- **One writer per checkout at a time.** While a child is writing, don't edit files yourself. Readers, such as reviewers and researchers, can run alongside each other.
- **Parallel writers need their own files or their own worktrees.** If you can't give each writer a separate set of files, give each task a lead.
- **A lead** is a separate thread started with `t3_thread_launch` and a `worktree` workspace. It runs this same loop in its own worktree, with its own children, and commits on its own branch. `delegate_task` can't place a child in another worktree, so a lead is the only isolated option. A lead adds a thread to the sidebar and leaves a worktree and branch behind, so use one only when the work must stay out of your checkout or must run in parallel. When the user asked for parallel or isolated work, that request covers launching leads. Otherwise propose the lead and ask first.
- **Do it yourself** when writing the brief would take longer than the work.

## 2. Write the brief

The child sees only your prompt. It has none of this conversation and none of the decisions made in it. Write the brief so a capable stranger could finish without asking anything:

- the goal, and what it is for;
- the exact files, branch, or commit to work from;
- what done looks like and how to check it;
- what to leave alone.

End every brief with the contract. Adapt the wording, keep every point:

> - Work only in this checkout. Put test repositories and scratch files under `/tmp`.
> - Don't ask questions. Choose the most reasonable reading and list your assumptions in the report.
> - Don't delegate to other agents, and don't commit.
> - Run commands in the foreground, even slow ones.
> - Make your final message the complete report: what you did, how you verified it, your assumptions, and anything unfinished. Earlier messages may not reach me.

Each point is there because leaving it out failed in testing:

- Reviewers testing a script ran it against the real repository by accident.
- A child that asks a question stops and waits, and its status still reads "running".
- Children can delegate too, with no depth limit. And you commit after verifying, so a child's commit would skip that check.
- A Claude child moved a slow command to the background, after which it could not be cancelled.
- For some providers T3 returns an early message as the result (see Known gaps), and a report spread over several messages is easy to lose.

For a lead, replace the third point with "Commit on your branch. Don't push or open a PR." For a reviewer, add "Don't edit files" and the shape you want back: severity, `file:line`, the defect in one sentence, a concrete failure scenario, and whether they confirmed it by running something.

Set `role`, a `title`, and a `clientRequestId` on every call. The request ID makes a retry return the same task; without one, a retry starts a second child. T3 prepends "Act as the <role> sub-agent for this task." to the brief, so don't write a role line of your own.

Set the model's effort option explicitly, from the model table. T3's default differs by model, and for some it is `low`.

## 3. Run it

- Start children with `mode: async` and end your turn. T3 wakes you when each finishes. Use `mode: wait` only for a single short task you need before you can continue; when several `wait` calls were issued together in testing, one was cut off mid-flight.
- A lead does not wake you, and a lead that delegates works across several turns. `t3_thread_wait` returns when the lead's current turn ends, which can be long before its work is done. So end a lead's brief with an instruction to `t3_thread_send` its final report to your thread ID with `mode: queue`, and treat that message as the signal. `t3_thread_wait` is enough only for a lead that does all the work itself in one turn. A callback is a request the lead may forget, so check the lead with `t3_thread_read` when it is overdue.
- Nothing wakes you if a child hangs. When you end your turn with work outstanding, tell the user what you are waiting on and roughly how long it should take, so a stall is visible to them.
- To change course mid-task, `t3_thread_send` to the child's thread. Its `childThreadId` is in the `delegate_task` result.
- A child that is running far longer than the task warrants may be waiting on a question. Check `t3_pending_request_list` for its thread and answer with `t3_pending_request_respond`.

## 4. Collect and verify

- Read the result with `task_status`. For an OpenCode child, including local GLM, read the last assistant message in its thread with `t3_thread_read` instead (see Known gaps).
- Treat the report as a claim. Before you act on it or pass it to the user, check it in proportion to what depends on it: read the diff, rerun the test it says passed, reproduce a finding. The `review-feedback` skill covers weighing findings.
- After reviewers finish, run `git status` to confirm nothing changed.
- To get fixes, send the findings to the implementer's thread with `t3_thread_send`. It still has its context, which a fresh child would lack.
- Commit yourself, after verifying. Tell the user what was delegated to which model and what you checked.

## Known gaps (checked 2026-10-02)

These are T3 bugs and limits, verified by experiment. Remove an entry when T3 fixes it.

- **OpenCode results are the first message, not the last.** T3 picks the newest message by timestamp, and the OpenCode 1.x adapter stamps them all alike at the end of the turn. Reading the thread works around it.
- **Local GLM runs one request at a time.** Two GLM children started together take turns, and each waits on the other. Run one at a time, and expect a review that builds test repositories to take 10 to 30 minutes.
- **`task_status` does not show a child blocked on a question.** It reads "running".
- **Background commands can't be cancelled.** `task_cancel` and `t3_thread_interrupt` stop only an active turn. The task still completes correctly when the command ends.
- **Steering Grok restarts its turn,** which kills the command in flight. Steering Codex does not.
- **`interactionMode: plan` is not enforced.** Grok, OpenCode, and Claude children all wrote files in plan mode. A reviewer stays read-only because the brief says so and you check afterwards.

## Example

The user asks for a fix to a script, reviewed before commit, from a thread already in its own worktree.

1. Shape: one writer, then reviewers, all in this checkout. No lead needed.
2. Delegate the fix to the implementation model, async, with the brief and contract. End the turn.
3. On wake-up, read the result and the diff. Then delegate two reviews in parallel, to models from different vendors, each told not to edit.
4. On wake-up, read both reviews (from the thread for a GLM reviewer), reproduce the findings that matter, and send the confirmed ones to the implementer's thread.
5. Verify the fixes, check `git status`, commit, and report what each model did and what was checked.
