# Moving an established checkout

Use `scripts/migrate.py --help` for one explicitly authorized move. Treat an older audit manifest as a candidate list, then refresh its evidence. The helper performs Git/filesystem operations only; the acting agent coordinates T3 through live tools. Never edit T3 databases or provider session files.

## Supported boundary

The helper supports a clean primary clone with an internal `.git` directory, committed HEAD, and healthy external linked worktrees that remain at their existing paths. Source and destination must be real paths on the same filesystem, with existing components spelled exactly as on disk; the destination parent already exists and is outside another checkout. The helper uses the platform's atomic exclusive rename API (tested on macOS; Linux implementation untested), preserves the directory inode, and runs Git's `worktree repair` with absolute pointers enforced.

It refuses dirty tracked/untracked state, index flags that can hide edits, submodules, nested repositories or worktrees, missing/locked worktrees, Git lock files or unfinished Git operations, separate Git directories, explicit `core.worktree`, and object alternates. Preparation also refuses effective config values containing the source path, naming the keys but withholding their values; resolve these consumers through a separate reviewed change before a move. Ignored files move with the directory; the helper does not delete or inventory their contents. Other path-sensitive configuration, external tools, processes without a cwd handle, and activity on other machines require the agent's investigation. Cwd inspection uses `lsof` for the current user, suppresses unrelated mount warnings, and refuses command errors or empty results; it cannot prove universal quiescence.

The config fingerprint includes repository, user, and system configuration and expanded includes. A path-conditional include that changes configuration at the destination is deliberately unsupported: `apply` restores the original path and reports the mismatch. Do not weaken the check to silently change identity, signing, hooks, or push behavior. A global config change after a successful move also blocks standalone rollback until investigated. The helper compares index entries (mode/object/stage/path), not cache bytes; routine `git status` cache refreshes are allowed.

Keep the journal in a private, persistent directory outside every affected checkout. It stores paths and preservation fingerprints, not config values or conversation bodies. It must be a newly named file; existing destinations, journals, and journal locks are never overwritten. A stale `.lock` after a crash needs inspection of its recorded PID before removal.

## Prepare the coordinated move

1. Verify repository/upstream/fork identity and the exact old/new paths. Inspect path consumers such as setup scripts, absolute configuration, shell sessions, editors, agents, and external worktrees. Do not change remotes as part of a path migration.
2. Read the live project and **all** its threads, including archived threads and review children. Record the original project ID/root/title/scripts, thread IDs/parents/branches/worktree bindings, run/provider metadata, settled/archive state, and ordered history item IDs. Classify each thread by provider and root versus retained-worktree binding. Before a batch, run an explicitly authorized bounded pilot for any provider/binding combination whose resumption must remain usable but is not yet proven. Known live proof covers root-bound Grok and Codex in an unchanged external worktree; Claude resumption and a changed root-bound Codex cwd remain unproven. Keep the snapshot outside affected paths. Paginate metadata reads; avoid exporting message bodies or credentials. Preserve IDs rather than recreating projects or transferring threads.
3. Confirm affected runs and tools are idle, and keep them idle during cutover. Do not move an active provider process. An existing cwd beneath any affected checkout blocks the helper. Use a coordinating thread whose cwd is outside all affected paths.
4. Create/inspect the destination owner directory, then prepare:

```sh
python3 scripts/migrate.py prepare --source /real/old/owner/repo \
  --destination /real/new/owner/repo --journal /private/evidence/move.json
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
4. Run `verify` against the journal and confirm Git still matches, the old path is absent, and no duplicate project was created. Record any host-created internal ref/config drift as a blocker to inspect, not something to force through. Finish only when filesystem, project/history preservation, and continuation have passed.

## Recovery

```sh
python3 scripts/migrate.py verify --journal /private/evidence/move.json
python3 scripts/migrate.py rollback --journal /private/evidence/move.json
```

Standalone rollback restores the original path and Git pointers **only when the saved Git state still matches**, ignoring solely the pointer changes owned by this move. It refuses later edits, new refs, configuration changes, an occupied old path, or active cwd processes. It can also recover an interrupted rename/repair when that state still matches. Inspect recovery failures instead of deleting paths, pruning records, resetting refs, or creating a compatibility symlink.

If the T3 update or continuation fails after Git moved, keep affected threads idle, roll back Git when eligible, and restore the saved project root/title through the API. Verify original bindings/history and their usability. If the API reply is ambiguous, read the current project before retrying. A failure to restore either side remains an incomplete migration; the helper journal alone does not claim T3 success.

## Evidence and tests

The fixture tests live in the dotfiles repository, not in the deployed skill. Run `python3 -m unittest tests.skills.test_repo_workspace_migrate` from the repository root (the parent of `chezmoi source-path`). They create disposable local Git fixtures, including temporary commits, and never move real checkouts. They exercise the real exclusive rename and Git repair, plus the failure and recovery paths. Cross-device refusal is simulated, so no second mounted filesystem is needed.

Live pilots proved two cases: a root-bound Grok continuation, and a Codex continuation in a retained external worktree that also preserved its review children. They did not prove a change to a root-bound Codex cwd, Claude continuation, moving active processes, dirty or submodule migrations, or cross-filesystem moves. Run a fresh bounded pilot before expanding into those cases.
