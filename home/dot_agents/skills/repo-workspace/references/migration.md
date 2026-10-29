# Moving an established checkout

Use `scripts/migrate.py --help` for one explicitly authorized move. Treat an older audit manifest as a candidate list, then refresh its evidence. The helper performs Git/filesystem operations only; the acting agent coordinates T3 through live tools. Never edit T3 databases or provider session files.

## Supported boundary

The helper supports a clean primary clone with an internal `.git` directory, committed HEAD, and healthy external linked worktrees that remain at their existing paths. Source and destination must be real paths on the same filesystem, with existing components spelled exactly as on disk; the destination parent already exists and is outside another checkout. The helper uses the platform's atomic exclusive rename API (fixture-tested on macOS, Linux, and Windows), preserves the directory inode, and runs Git's `worktree repair` with absolute pointers enforced.

It refuses dirty tracked/untracked state, index flags that can hide edits, submodules, nested repositories or worktrees, missing/locked worktrees, Git lock files or unfinished Git operations (`gh stack`'s empty `gh-stack.lock` and `gh-stack-operation.lock` in the Git directory are allowed while no process holds them open; on Windows a held one makes the rename fail), separate Git directories, explicit `core.worktree`, and object alternates. Preparation also refuses effective config values containing the source path, naming the keys but withholding their values; resolve these consumers through a separate reviewed change before a move. Ignored files move with the directory; the helper does not delete or inventory their contents. Other path-sensitive configuration, external tools, processes without a cwd handle, and activity on other machines require the agent's investigation. Cwd inspection uses `lsof` for the current user, suppresses unrelated mount warnings, and refuses command errors or empty results; it cannot prove universal quiescence. Windows has no such listing. There the rename itself fails while any process has its cwd or an open file inside the primary checkout, but processes in retained worktrees go unchecked, so confirm they are idle yourself.

Some states look alarming but are harmless. Each needs its own narrow handling, never a blanket ignore:

- **macOS provenance.** The kernel stamps `com.apple.provenance` onto the renamed root and onto the worktree pointer files Git rewrites in place. This helper does not compare extended attributes. Any tool that does should skip that attribute by exact name and keep comparing the others.
- **Vendored `.gitmodules`.** The submodule check reads only the checkout's top-level `.gitmodules` and `git submodule status`. A `.gitmodules` inside a package directory such as `node_modules` declares nothing and moves with the directory.
- **Stale `AUTO_MERGE`.** Git can leave an `AUTO_MERGE` file in a Git directory after a conflicted merge, sometimes naming an object that no longer exists. It is not an operation in progress. It moves unchanged; don't delete it.
- **Broken evidence.** Dangling links, missing worktree attachments, and stale markers that existed before the move are preserved as they are, not pruned or repaired as a side effect.

The config fingerprint includes repository, user, and system configuration and expanded includes. A path-conditional include that changes configuration at the destination is deliberately unsupported: `apply` restores the original path and reports the mismatch. Do not weaken the check to silently change identity, signing, hooks, or push behavior. A global config change after a successful move also blocks standalone rollback until investigated. The helper compares index entries (mode/object/stage/path), not cache bytes; routine `git status` cache refreshes are allowed.

Keep the journal in a private, persistent directory outside every affected checkout. It stores paths and preservation fingerprints, not config values or conversation bodies. It must be a newly named file; existing destinations, journals, and journal locks are never overwritten. A stale `.lock` after a crash needs inspection of its recorded PID before removal.

## Prepare the coordinated move

1. Verify repository/upstream/fork identity, the category and alias of the destination, and the exact old and new paths. Inspect path consumers such as setup scripts, absolute configuration, shell sessions, editors, agents, and external worktrees. Do not change remotes as part of a path migration.
2. Read the live project and **all** its threads, including archived threads and review children. The native project thread listing currently returns active threads only. List archived and deleted records with the `t3-thread-search` skill's `--include-deleted --path <primary checkout>` lookup and check its `truncated` flag, then read surviving IDs natively. Record the original project ID/root/title/scripts, thread IDs/parents/branches/worktree bindings, run/provider metadata, settled/archive state, and ordered history item IDs. Classify each thread by provider and root versus retained-worktree binding. Before a batch, run an explicitly authorized bounded pilot for any provider/binding combination whose resumption must remain usable but is not yet proven. Known live proof covers root-bound Grok, Claude, and Codex after a root change, and Codex and Claude in an unchanged external worktree. Keep the snapshot outside affected paths. Paginate metadata reads; avoid exporting message bodies or credentials. Preserve IDs rather than recreating projects or transferring threads.
3. Confirm affected runs and tools are idle, and keep them idle during cutover. Do not move an active provider process. An existing cwd beneath any affected checkout blocks the helper. Use a coordinating thread whose cwd is outside all affected paths.
4. Create or inspect the destination category directory, then prepare:

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

The helper rechecks its snapshot, moves the primary directory without overwriting a destination, repairs worktree pointers, and verifies all refs, HEADs/branches, index entries, configuration, registration paths, and inodes. If repair/verification fails within this call, it checks ownership of the moved inode, attempts to move it back without overwriting anything, repairs the old pointers, then verifies preservation. It does not reset any content, refs, or configuration. This immediate undo differs from a later standalone rollback, which requires the saved state to match before moving.

Read the journal phase after any error: `prepared` after a rename refusal means the source inode never moved; `rolled_back` means original Git state was restored; `recovery_required` requires inspection of both paths. A competing destination is preserved and leaves the journal `prepared`. If concurrent changes or a recovery failure prevent full verification, the helper reports the incomplete recovery rather than claiming success. Never retry an interrupted operation blindly. A successful `apply` can be repeated safely while the saved state still matches; after rollback, prepare a new journal for another attempt.

2. Update the **existing** T3 project root/title through the live project API, retaining its ID and scripts. Linked worktree paths remain unchanged. Compare saved thread bindings, lineage, run metadata, and history IDs before continuing any thread; no unexplained loss or replacement is acceptable.
3. Continue the relevant existing conversation with a tightly scoped, read-only test. Have it report `pwd`, Git top-level/common directory, HEAD, branch, and status, and recall its prior task. Do not supply the expected cwd or let it use `cd`/an explicit workdir: that would conceal a stale binding. Inspect actual command output, not just the agent's claim. This test appends history; verify the original ordered prefix survives and restore prior settled/archive state where appropriate. It must not edit, fetch, build, delegate, or publish.
4. Run `verify` against the journal and confirm Git still matches, the old path is absent, and no duplicate project was created. Finish only when filesystem, project/history preservation, and continuation have passed.

### Checkpoint refs from the continuation

T3 records a checkpoint commit for each provider turn, even a read-only one, so after the continuation `verify` refuses with `refs` changed. Do not weaken the check, delete the refs, or edit the journal. Instead:

1. List the new refs with `git for-each-ref refs/t3` and match each name to its thread and the continuation run: the ordinal is that thread's run ordinal. Anything you cannot account for that way is a blocker to inspect.
2. Record exactly those refs, each with its full object ID and the checkout its thread is bound to:

```sh
python3 scripts/migrate.py record-checkpoints --journal /private/evidence/move.json \
  --checkpoint refs/t3/orchestration-v2/checkpoints/<thread>/ordinal/<n> <oid> /real/dev-root/Contribute/talos
```

The helper accepts only `refs/t3/orchestration-v2/checkpoints/<id>/ordinal/<n>` names. Each must be a commit whose message names that same ref (`t3 checkpoint ref=<ref>`), whose parent is its checkout's saved HEAD, and whose tree equals that clean HEAD tree. The helper cannot see T3 lineage: when two checkouts share a HEAD, their checkpoints are indistinguishable by content, so the checkout you name comes from the thread binding you verified in step 1. Every other ref, as well as HEAD, branch, index, config, worktree pointer, and inode, must still match the saved snapshot, and no unlisted ref may appear. The original snapshot is kept unchanged; the accepted refs are added to the journal, and later `verify` runs account for them. Refusal leaves the journal untouched.

## Recovery

```sh
python3 scripts/migrate.py verify --journal /private/evidence/move.json
python3 scripts/migrate.py rollback --journal /private/evidence/move.json
```

Standalone rollback restores the original path and Git pointers **only when the saved Git state still matches**, before any provider work resumes, ignoring solely the pointer changes owned by this move. It refuses later edits, new refs, configuration changes, an occupied old path, or active cwd processes. It can also recover an interrupted rename/repair when that state still matches. Inspect recovery failures instead of deleting paths, pruning records, resetting refs, or creating a compatibility symlink.

Once a continuation's checkpoints are recorded, the journal refuses rollback: the threads have new history that moving the directory back cannot undo. After that, or after any later legitimate work, the journal is evidence rather than a live invariant, and `verify` will refuse once ordinary work changes the checkout. To revert such a move, plan a new move in the reverse direction with a new journal and its own T3 update and continuation check.

If the T3 update or continuation fails after Git moved, keep affected threads idle, roll back Git when eligible, and restore the saved project root/title through the API. Verify original bindings/history and their usability. If the API reply is ambiguous, read the current project before retrying. A failure to restore either side remains an incomplete migration; the helper journal alone does not claim T3 success.

## Evidence and tests

The fixture tests live in the dotfiles repository, not in the deployed skill. Run `python3 -m unittest tests.skills.test_repo_workspace_migrate` from the repository root, which is `git -C "$(chezmoi source-path)" rev-parse --show-toplevel`. They create disposable local Git fixtures, including temporary commits, and never move real checkouts. They exercise the real exclusive rename and Git repair, the failure and recovery paths, and checkpoint recording, including refusals for changed or extra refs, wrong objects, and unrelated drift. Cross-device refusal is simulated, so no second mounted filesystem is needed.

Live macOS moves proved continuations at a changed root for Grok, Claude, and Codex, and Codex and Claude continuations in retained external worktrees, with prior context and all original thread history intact. A Codex thread bound to a moved non-Git workspace also resumed. The root-bound Codex test supplied no cwd and did not change directories. `record-checkpoints` reconciled the live journals after those continuations once it accepted the first checkpoint's `ordinal/0`.

Other cases were moved live, but not by this helper: Windows moves, dirty, unborn, nested, and submodule checkouts, and checkouts with missing worktree registrations. One-off tooling outside this skill handled them, so this helper's refusals for those cases still stand. This helper's Windows and Linux support has been tested only on fixtures in CI, with no live move on either. Moving active processes and cross-filesystem moves are untested. Run a fresh bounded pilot before expanding into any of these cases.
