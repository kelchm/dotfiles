# Moving an established checkout

Use `scripts/migrate.py --help` for one explicitly authorized move. Treat an older audit manifest as a candidate list, then refresh its evidence. The helper performs Git/filesystem operations only; the acting agent coordinates T3 through live tools. Never edit T3 databases or provider session files.

## Supported boundary

The helper supports a primary clone with an internal `.git` directory, committed HEAD, and healthy external linked worktrees that remain at their existing paths. Source and destination must be real paths on the same filesystem, with existing components spelled exactly as on disk; the destination parent already exists. Either path may sit inside another checkout, such as a [workspace](#workspaces) repository, only where that checkout ignores it: `git check-ignore` decides, and an unignored path, or one the enclosing checkout tracks as a file or directory in any letter case, is refused. Rollback checks the old path again before moving back. The helper uses the platform's atomic exclusive rename API (live-tested on macOS, Linux, and Windows), preserves the directory inode, and runs Git's `worktree repair` with absolute pointers enforced.

It refuses uncommitted tracked or untracked changes unless prepared with `--allow-dirty` (below), index flags that can hide edits, submodules, nested repositories or worktrees, missing/locked worktrees, Git lock files or unfinished Git operations (`gh stack`'s empty `gh-stack.lock` and `gh-stack-operation.lock` in the Git directory are allowed while no process holds them open; on Windows a held one makes the rename fail), separate Git directories, explicit `core.worktree`, and object alternates. Preparation also refuses effective config values containing the source path, naming the keys but withholding their values; resolve these consumers through a separate reviewed change before a move. Ignored files move with the directory; the helper does not delete or inventory their contents. Other path-sensitive configuration, external tools, processes without a cwd handle, and activity on other machines require the agent's investigation. Cwd inspection uses `lsof` for the current user, suppresses unrelated mount warnings, and refuses command errors or empty results; it cannot prove universal quiescence. A refusal names the process and its command. Windows has no such listing. There the rename itself fails while any process has its cwd or an open file inside the primary checkout, but processes in retained worktrees go unchecked, so settle every thread bound to the checkout or its worktrees and confirm they are idle yourself.

Uncommitted work is common and is not a reason to stash, commit, reset, or delete anything. When `prepare` refuses a dirty checkout, it lists the changed and untracked paths. Review them, confirm nothing is still writing to the checkout, then run `prepare` again with `--allow-dirty`. The journal then fingerprints the status and the content of every listed path, in the primary checkout and each retained worktree, and `apply`, `verify`, and `rollback` require it unchanged, so an edit during the move is refused or undone like any other drift. The rename carries the files as they are. A T3 checkpoint taken in a dirty checkout snapshots that dirty tree rather than HEAD, so `record-checkpoints` refuses it, and every later `verify` and `rollback` refuses on the unrecorded ref. For a dirty checkout with T3 threads, run `verify` before the continuation test, and plan any later reversal as a new move. Threads bound to clean checkouts in the same move are unaffected.

Some states look alarming but are harmless. Each needs its own narrow handling, never a blanket ignore:

- **macOS provenance.** The kernel stamps `com.apple.provenance` onto the renamed root and onto the worktree pointer files Git rewrites in place. This helper does not compare extended attributes. Any tool that does should skip that attribute by exact name and keep comparing the others.
- **Vendored `.gitmodules`.** The submodule check reads only the checkout's top-level `.gitmodules` and `git submodule status`. A `.gitmodules` inside a package directory such as `node_modules` declares nothing and moves with the directory.
- **Stale `AUTO_MERGE`.** Git can leave an `AUTO_MERGE` file in a Git directory after a conflicted merge, sometimes naming an object that no longer exists. It is not an operation in progress. It moves unchanged; don't delete it.
- **Broken evidence.** Dangling links, missing worktree attachments, and stale markers that existed before the move are preserved as they are, not pruned or repaired as a side effect.

The config fingerprint includes repository, user, and system configuration and expanded includes. A path-conditional include that changes configuration at the destination is deliberately unsupported: `apply` restores the original path and reports the mismatch. Do not weaken the check to silently change identity, signing, hooks, or push behavior. A global config change after a successful move also blocks standalone rollback until investigated. The helper compares index entries (mode/object/stage/path), not cache bytes; routine `git status` cache refreshes are allowed.

Keep the journal in a private, persistent directory outside every affected checkout. It stores paths and preservation fingerprints, not config values or conversation bodies. It must be a newly named file; existing destinations, journals, and journal locks are never overwritten. A stale `.lock` after a crash needs inspection of its recorded PID before removal.

## Prepare the coordinated move

1. Verify repository/upstream/fork identity, the category and alias of the destination, and the exact old and new paths. Inspect path consumers such as setup scripts, absolute configuration, shell sessions, editors, agents, external worktrees, and the [state keyed by the old path](#state-keyed-by-the-old-path). Do not change remotes as part of a path migration. On Windows, don't set `GIT_SSH_COMMAND` to a bare `ssh` while checking remotes: it overrides `core.sshCommand` (for example Windows OpenSSH, which can reach the 1Password agent) with Git's bundled ssh and produces false "Permission denied (publickey)" results.
2. Read the live project and **all** its threads, including archived threads and review children. The native project thread listing currently returns active threads only. List archived and deleted records with the `t3-thread-search` skill's `--include-deleted --path <primary checkout>` lookup and check for truncation (`truncated` with `--json`, or `(truncated)` after the result count), then read surviving IDs natively. Record the original project ID/root/title/scripts, thread IDs/parents/branches/worktree bindings, run/provider metadata, settled/archive state, and ordered history item IDs. Classify each thread by provider and root versus retained-worktree binding. Before a batch, run an explicitly authorized bounded pilot for any provider/binding combination whose resumption must remain usable but is not yet proven. Known live proof covers root-bound Grok, Claude, and Codex after a root change, and Codex and Claude in an unchanged external worktree. Keep the snapshot outside affected paths. Paginate metadata reads; avoid exporting message bodies or credentials. `scripts/t3_snapshot.py save --project <id> --out <file>` records most of this read-only for each named project, archived and deleted threads included, with message IDs but no text; name every affected project, including a workspace's. Run metadata stays with native reads. Preserve IDs rather than recreating projects or transferring threads.
3. Confirm affected runs and tools are idle, and keep them idle during cutover. Do not move an active provider process. An existing cwd beneath any affected checkout blocks the helper. Use a coordinating thread whose cwd is outside all affected paths. Idle T3 provider sessions also keep a cwd in checkouts and worktrees: `claude` processes, and Codex `node_repl` children of `codex app-server`. Settle the thread that owns one, and T3 releases it within about 5 seconds; never kill it. On macOS, an idle T3 integrated terminal whose cwd is in a retained worktree is enough to make `prepare` refuse; ask the owner to close it. On Linux, unreadable `/proc/<pid>/cwd` entries for other users' processes and for your own `systemd --user` and `(sd-pam)` are expected, not blockers.
4. Create or inspect the destination category directory. Claude Code's `Agent` tool with `isolation: "worktree"` leaves worktrees under the main checkout at `.claude/worktrees/agent-*`, even when the parent session ran in a T3 worktree, and never removes them, so `prepare` refuses them as nested worktrees. Move each one out first with `git worktree move` to a uniquely named folder under an existing worktree area; a live move of 21, one with uncommitted edits, preserved all their state. Then prepare:

```sh
python3 scripts/migrate.py prepare --source /real/old/path/talos \
  --destination /real/dev-root/Contribute/talos --journal /private/evidence/move.json
```

Preparation writes a snapshot but does not relocate anything. Review the exact paths and retained worktrees, T3 update, continuation test, and rollback plan. Existing user authorization for that concrete move suffices; an audit request alone does not authorize applying it.

## Cut over and prove continuation

1. Refresh live T3 run state immediately before applying. Run:

```sh
python3 scripts/migrate.py apply --journal /private/evidence/move.json
```

The helper rechecks its snapshot, moves the primary directory without overwriting a destination, repairs worktree pointers, and verifies all refs and the stash list, HEADs/branches, index entries, configuration, registration paths, and inodes. If repair/verification fails within this call, it checks ownership of the moved inode, attempts to move it back without overwriting anything, repairs the old pointers, then verifies preservation. It does not reset any content, refs, or configuration. This immediate undo differs from a later standalone rollback, which requires the saved state to match before moving.

Read the journal phase after any error: `prepared` after a rename refusal means the source inode never moved; `rolled_back` means original Git state was restored; `recovery_required` requires inspection of both paths. A competing destination is preserved and leaves the journal `prepared`. If concurrent changes or a recovery failure prevent full verification, the helper reports the incomplete recovery rather than claiming success. Never retry an interrupted operation blindly. A successful `apply` can be repeated safely while the saved state still matches; after rollback, prepare a new journal for another attempt.

2. Update the **existing** T3 project root/title through the live project API, retaining its ID and scripts. Linked worktree paths remain unchanged. Compare saved thread bindings, lineage, run metadata, and history IDs before continuing any thread; no unexplained loss or replacement is acceptable. `scripts/t3_snapshot.py compare --before <file>` fails on a missing or deleted thread, a changed binding or lineage, and lost or reordered messages. It lists root, title, script, archive, settled, and tracked-folder changes and appended messages as notes, each of which needs an explanation. T3 can take a few seconds to rediscover a workspace's tracked folders after a re-root, so re-read the project for up to about 30 seconds before treating an empty or partial list as a failure.
3. Trust the new path's `mise` configs (see [below](#state-keyed-by-the-old-path)), then continue the relevant existing conversation with a tightly scoped, read-only test. Have it report `pwd`, Git top-level/common directory, HEAD, branch, and status, and recall its prior task. Do not supply the expected cwd or let it use `cd`/an explicit workdir: that would conceal a stale binding. Inspect actual command output, not just the agent's claim. This test appends history; verify the original ordered prefix survives and restore prior settled/archive state where appropriate. It must not edit, fetch, build, delegate, or publish.
4. Run `verify` against the journal and `t3_snapshot.py compare` again, and confirm Git still matches, the old path is absent, and no duplicate project was created. Finish only when filesystem, project/history preservation, and continuation have passed.

### Checkpoint refs from the continuation

T3 records a checkpoint commit for each provider turn, even a read-only one, so after the continuation `verify` refuses with `refs` changed. Do not weaken the check, delete the refs, or edit the journal. Instead:

1. List the new refs with `git for-each-ref refs/t3` and match each name to its thread and the continuation run: the ordinal is that thread's run ordinal. Anything you cannot account for that way is a blocker to inspect.
2. Record exactly those refs, each with its full object ID and the checkout its thread is bound to:

```sh
python3 scripts/migrate.py record-checkpoints --journal /private/evidence/move.json \
  --checkpoint refs/t3/orchestration-v2/checkpoints/<thread>/ordinal/<n> <oid> /real/dev-root/Contribute/talos
```

The helper accepts only `refs/t3/orchestration-v2/checkpoints/<id>/ordinal/<n>` names. Each must be a commit whose message names that same ref (`t3 checkpoint ref=<ref>`, optionally followed by a blank line and trailer lines), whose parent is its checkout's saved HEAD, and whose tree equals that clean HEAD tree. The helper cannot see T3 lineage: when two checkouts share a HEAD, their checkpoints are indistinguishable by content, so the checkout you name comes from the thread binding you verified in step 1. Every other ref, as well as HEAD, branch, index, config, worktree pointer, and inode, must still match the saved snapshot, and no unlisted ref may appear. The original snapshot is kept unchanged; the accepted refs are added to the journal, and later `verify` runs account for them. Refusal leaves the journal untouched.

### State keyed by the old path

Some tools key state by the checkout path, outside Git and T3:

- **`mise` trust.** The new path's `mise.toml` starts untrusted. Where a provider such as `claude` launches through a `mise` command wrapper, it then exits 1 and T3 reports "The provider could not start this turn". The old path's trust entry would remain and silently trust whatever is later cloned there, and `mise trust --untrust` refuses a path that no longer exists, so untrust the old path just before `apply` (and trust it again if you roll back). In a workspace, trust each checkout inside it; T3 worktrees are new paths and start untrusted too.
- **Claude auto-memory** is keyed to the main checkout's path and shared by all its worktrees, so the move orphans it. The key spells each `/` and `.` as `-`, so `…/ritornel/lab` and `…/ritornel-lab` share one and memory and transcripts carry over, while `…/ritornel` to `…/ritornel/ritornel` changes it. Ask the owner which checkout keeps it. Moving the `memory/` folder to the new path's project folder under `~/.claude/projects` is fine; it is not a provider session file.
- **Claude session transcripts** stay under the old path's project folder. Root-bound Claude threads still resumed at the new path on macOS, Linux, and Windows (Claude Code 2.1.327 and 2.1.328) and keep writing there, so whatever is later checked out at the old path inherits them, for example in `claude --resume`.
- **T3's GitHub identity** for a project is cached by path for about 15 minutes. After a remote change, or when the old path is reused for a different repository, the project shows the old `owner/repo` until the cache expires. Don't use its PR features until it refreshes.

## Workspaces

A [workspace](../SKILL.md#where-a-checkout-lives) is a guidance repository whose folder holds other checkouts that it ignores. The helper moves one checkout into or out of it like any other move, as long as the workspace's `.gitignore` already ignores that path. It still refuses to move a folder with checkouts inside it, so a workspace never moves as one unit.

To create a workspace from existing checkouts:

1. Make sure the workspace repository exists on its remote, with `/<alias>/` in its `.gitignore` for each checkout it will hold.
2. If a checkout already occupies the workspace path, as `Personal/ritornel` did before becoming `Personal/ritornel/ritornel`, move it to a temporary sibling such as `Personal/ritornel-moving` first, with its own journal. A directory can't be renamed into itself, and two ordinary journaled moves are simpler to recover than one with a hidden intermediate step. Leave its T3 project alone until the second move.
3. Clone the workspace repository at the workspace path.
4. Move each checkout in with `prepare` and `apply`, one journal each.
5. Create the workspace's T3 project at the folder, or reuse a workspace project already rooted there. Don't turn a checkout's own project into it, even one rooted at the workspace path before the hop: its root-bound threads would then resume in the workspace folder instead of their checkout. Re-root each checkout's old project to its new path, check it with `t3_snapshot.py compare`, then archive it. Never delete one. Wait for the workspace project's tracked folders as described above.
6. Run `mise trust` in each checkout, then continue a thread in each as usual.

To move a checkout out, run the helper from `<workspace>/<alias>` to its new home. Once the move and its continuation are verified, remove the alias from the workspace's `.gitignore`, guidance, and setup steps in an ordinary commit; rollback refuses to return a checkout to a path the workspace no longer ignores. To relocate a whole workspace, clone the workspace repository at the new path, move each checkout into it, and retire the old workspace checkout under the usual retirement rules once it holds nothing unpushed.

## Recovery

```sh
python3 scripts/migrate.py verify --journal /private/evidence/move.json
python3 scripts/migrate.py rollback --journal /private/evidence/move.json
```

Standalone rollback restores the original path and Git pointers **only when the saved Git state still matches**, before any provider work resumes, ignoring solely the pointer changes owned by this move. It refuses later edits, new refs, configuration changes, an occupied old path, or active cwd processes. It can also recover an interrupted rename/repair when that state still matches. Inspect recovery failures instead of deleting paths, pruning records, resetting refs, or creating a compatibility symlink.

Once a continuation's checkpoints are recorded, the journal refuses rollback: the threads have new history that moving the directory back cannot undo. After that, or after any later legitimate work, the journal is evidence rather than a live invariant, and `verify` will refuse once ordinary work changes the checkout. To revert such a move, plan a new move in the reverse direction with a new journal and its own T3 update and continuation check.

If the T3 update or continuation fails after Git moved, keep affected threads idle, roll back Git when eligible, and restore the saved project root/title through the API. Verify original bindings/history and their usability. If the API reply is ambiguous, read the current project before retrying. A failure to restore either side remains an incomplete migration; the helper journal alone does not claim T3 success.

## Evidence and tests

The fixture tests live in the dotfiles repository, not in the deployed skill. Run `python3 -m unittest tests.skills.test_repo_workspace_migrate tests.skills.test_repo_workspace_t3_snapshot` from the repository root, which is `git -C "$(chezmoi source-path)" rev-parse --show-toplevel`. They create disposable local Git fixtures, including temporary commits, and a disposable T3 store, and never move real checkouts or open a real store. They exercise the real exclusive rename and Git repair, the failure and recovery paths, moves into and out of an ignoring workspace including the creation sequence above, and checkpoint recording, including refusals for changed or extra refs, wrong objects, and unrelated drift. Cross-device refusal is simulated, so no second mounted filesystem is needed.

Live macOS moves proved continuations at a changed root for Grok, Claude, and Codex, and Codex and Claude continuations in retained external worktrees, with prior context and all original thread history intact. A Codex thread bound to a moved non-Git workspace also resumed. The root-bound Codex test supplied no cwd and did not change directories. `record-checkpoints` reconciled the live journals after those continuations once it accepted the first checkpoint's `ordinal/0`. A later move of a dirty checkout, prepared with `--allow-dirty`, continued a root-bound Claude thread and a worktree-bound Codex thread.

On Windows, with Microsoft's VFS build of Git, this helper round-tripped a disposable repository with a retained worktree, a fresh clone with a retained worktree, and a clean checkout registered as a T3 project. Each returned with the same file ID, HEAD, refs, and stashes, and the project and its threads were unchanged. A process with its cwd inside the checkout made `apply` refuse with the journal still `prepared`. A real checkout with 3 retained worktrees, one with 41 uncommitted changes, then moved live with `--allow-dirty`.

On Linux, a real checkout on btrfs with 2 retained worktrees moved live, and Claude and Codex threads continued.

On 2026-11-21 the Ritornel app and lab checkouts moved into a new `ritornel/workspace` on macOS, Linux, and Windows, with the app hopping through a temporary sibling. The helper then refused workspace destinations, so the workspace repository was initialized in place afterwards; the `git check-ignore` route above is covered by fixtures only.

Unborn, nested, and submodule checkouts, and checkouts with missing worktree registrations, were moved live by one-off tooling outside this skill, so this helper's refusals for those cases still stand. Moving active processes and cross-filesystem moves are untested. Run a fresh bounded pilot before expanding into any of these cases.
