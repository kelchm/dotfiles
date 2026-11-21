# Moving an established checkout

`scripts/migrate.py` moves one explicitly authorized checkout; see `--help`. It changes Git and the filesystem only. The acting agent coordinates T3 through live tools and never edits T3's database or provider session files. Treat an older audit manifest as a candidate list and refresh its evidence.

## What the helper supports

It moves a primary clone with an internal `.git` directory and a committed HEAD. Its healthy linked worktrees stay where they are, and `git worktree repair` rewrites their pointers as absolute paths. Source and destination are real paths on one filesystem, spelled exactly as on disk, and the destination's parent already exists. The rename is atomic and never overwrites anything (live-tested on macOS, Linux, and Windows), so the directory keeps its inode.

Either path may sit inside another checkout, such as a [workspace](#workspaces), only where that checkout ignores it. `git check-ignore` decides, and the helper refuses a path the enclosing checkout tracks as a file or directory in any letter case. Rollback checks the old path again before moving back.

It refuses what it can't move losslessly: submodules, nested repositories or worktrees, missing or locked worktrees, separate Git directories, explicit `core.worktree`, object alternates, index flags that hide edits, Git lock files, and unfinished Git operations. `gh stack`'s empty `gh-stack.lock` and `gh-stack-operation.lock` are allowed while no process holds them. It also refuses config values that contain the source path, naming the keys but not the values; resolve those in a separate reviewed change first.

Uncommitted work is common and is never a reason to stash, commit, reset, or delete. `prepare` lists the changed and untracked paths. Review them, confirm nothing is still writing, and prepare again with `--allow-dirty`. The journal then fingerprints that work in every checkout, and any change to it during the move is refused or undone like other drift. Ignored files move with the directory, unexamined.

Processes are checked with `lsof` for the current user's cwd handles; a refusal names the process and its command. That check can't prove that nothing else is using the checkout. On Windows there is no cwd listing. The rename itself fails while anything holds the primary checkout, but nothing checks retained worktrees, so settle every thread bound to them and confirm they're idle yourself. Other path-sensitive tools and other machines are yours to investigate.

The config fingerprint covers repository, user, and system config with includes expanded. A path-conditional include that changes config at the destination makes `apply` move back and report it; never weaken that check, since it guards identity, signing, hooks, and push behavior. Index entries are compared, not cache bytes, so routine `git status` refreshes are fine.

Keep the journal in a new file in a private, persistent directory outside every affected path. It holds paths and fingerprints, not config values or conversations. Nothing overwrites an existing destination, journal, or lock; inspect a stale `.lock`'s recorded PID before removing it.

These look alarming but are harmless. Handle each narrowly, never with a blanket ignore:

- **macOS provenance.** The kernel stamps `com.apple.provenance` on the renamed root and on worktree pointer files Git rewrites. Any tool comparing extended attributes should skip exactly that one.
- **Vendored `.gitmodules`.** Only the top-level `.gitmodules` declares submodules; one inside `node_modules` moves with the directory.
- **Stale `AUTO_MERGE`.** Left after a conflicted merge, sometimes naming a missing object. It isn't an operation in progress; leave it.
- **Broken evidence.** Dangling links, missing worktree attachments, and stale markers from before the move are preserved, never pruned or repaired.

## Prepare

1. Verify the repository, its upstream and fork, the destination category and alias, and the exact paths. Inspect path consumers: setup scripts, absolute config, shells, editors, agents, external worktrees, and the [state keyed by the old path](#state-keyed-by-the-old-path). Don't change remotes during a move. On Windows, don't set `GIT_SSH_COMMAND` to a bare `ssh` while checking remotes: it bypasses `core.sshCommand` and produces false "Permission denied (publickey)" results.
2. Record T3's state for every affected project, including a workspace's, and keep the record outside affected paths:
   - the project's ID, root, title, and scripts
   - every thread, including archived ones and review children. Native listings return active threads only, so add archived and deleted ones with the `t3-thread-search` skill's `--include-deleted --path <checkout>` lookup and check that it wasn't truncated.
   - for each thread: parent, provider, branch, root or worktree binding, settled and archived state, and its item count and latest item ID

   Record IDs and counts, not message text or credentials. Never recreate a project or transfer a thread to "fix" a move.
3. Before a batch, pilot any provider and binding combination not yet proven, with explicit authorization. Proven so far: root-bound Grok, Claude, and Codex after a root change, and Claude and Codex in an unchanged external worktree.
4. Make affected runs idle and keep them idle. Work from a thread whose cwd is outside every affected path. Idle provider sessions hold a cwd too: `claude` processes, and Codex `node_repl` children of `codex app-server`. Settling the owning thread releases one within about 5 seconds; never kill it. An idle T3 integrated terminal in a retained worktree also blocks `prepare`; ask its owner to close it. On Linux, unreadable `/proc/<pid>/cwd` entries for other users and for your own `systemd --user` and `(sd-pam)` are expected.
5. Move Claude Code's `Agent` worktrees out first. `isolation: "worktree"` leaves them at `.claude/worktrees/agent-*` under the main checkout, where `prepare` refuses them as nested. Use `git worktree move` to a uniquely named folder under an existing worktree area. Then prepare:

```sh
python3 scripts/migrate.py prepare --source /real/old/path/talos \
  --destination /real/dev-root/Contribute/talos --journal /private/evidence/move.json
```

`prepare` only records. Review the paths, retained worktrees, T3 update, continuation test, and rollback plan. User authorization for this concrete move is enough; an audit request is not.

## Cut over

1. Refresh live T3 run state, then:

```sh
python3 scripts/migrate.py apply --journal /private/evidence/move.json
```

`apply` rechecks the snapshot, renames, repairs worktree pointers, and verifies refs, the stash list, every HEAD and branch, index entries, config, registrations, and the inode. If repair or verification fails, it moves the checkout back within the same call, without resetting anything. After an error, read the journal's phase: `prepared` means nothing moved, `rolled_back` means the original state is back, and `recovery_required` means inspect both paths. Never retry an interrupted operation blindly. A successful `apply` is safe to repeat.

2. Update the **existing** project's root and title through the live API, keeping its ID and scripts. Compare its threads with your record: every thread present, bindings and lineage unchanged, and nothing lost from any history. A workspace project can take a few seconds to list its tracked folders after a re-root; re-read it for up to about 30 seconds before calling that a failure.
3. Trust the new path's `mise` config, then continue an existing thread with a read-only test. Have it report `pwd`, Git top-level and common directory, HEAD, branch, and status, and recall its prior task. Don't tell it the expected cwd or let it `cd`: that would hide a stale binding. Check the command output, not just the agent's claim. The test must not edit, fetch, build, delegate, or publish. Its history only grows; restore settled or archived state if it changed.
4. Record the continuation's checkpoints (below), run `verify`, and compare T3 with your record again. Finish only when Git, T3 history, and continuation all pass, the old path is gone, and no duplicate project exists.

### Checkpoint refs

T3 commits a checkpoint for every provider turn, so after the continuation `verify` refuses with `refs` changed. Don't weaken the check, delete the refs, or edit the journal. List them with `git for-each-ref refs/t3`, match each to its thread (the ordinal is the thread's run ordinal), treat any you can't account for as a blocker, and record exactly those:

```sh
python3 scripts/migrate.py record-checkpoints --journal /private/evidence/move.json \
  --checkpoint refs/t3/orchestration-v2/checkpoints/<thread>/ordinal/<n> <oid> /real/dev-root/Contribute/talos
```

The helper checks that each is a T3 checkpoint of its checkout's clean saved HEAD and that nothing else changed. It can't tell two checkouts with the same HEAD apart, so name the checkout from the thread binding you verified. A checkpoint taken in a dirty checkout snapshots the dirty tree and is refused; for a dirty move with T3 threads, run `verify` before the continuation.

### State keyed by the old path

- **`mise` trust.** The new path starts untrusted, and a provider launched through a `mise` wrapper then fails with "The provider could not start this turn". The old path's entry would silently trust whatever is cloned there later, and `mise trust --untrust` refuses a missing path, so untrust the old path just before `apply` and trust it again on rollback. In a workspace, trust each checkout inside it; new T3 worktrees start untrusted too.
- **Claude auto-memory** is keyed to the main checkout's path, so a move orphans it. The key spells `/` and `.` as `-`: `…/ritornel/lab` and `…/ritornel-lab` share a key, while `…/ritornel` to `…/ritornel/ritornel` changes it. Ask the owner which checkout keeps it; moving its `memory/` folder under `~/.claude/projects` is fine.
- **Claude transcripts** stay under the old key. Moved root-bound threads still resume and keep writing there, so whatever later lands at the old path inherits them in `claude --resume`.
- **T3's GitHub identity** is cached by path for about 15 minutes. Avoid its PR features until it refreshes after a remote change or a reused path.

## Workspaces

A [workspace](../SKILL.md#where-a-checkout-lives) checkout ignores the checkouts inside it, so the helper moves one in or out like any other move once the `.gitignore` entry exists. It never moves a workspace with its checkouts as one unit.

To create one from existing checkouts:

1. Make sure the workspace repository has `/<alias>/` in its `.gitignore` for each checkout.
2. If a checkout occupies the workspace path, as the app at `Personal/ritornel` did, move it to a temporary sibling such as `Personal/ritornel-moving` first. A directory can't be renamed into itself, and two ordinary moves are easier to recover than one with a hidden intermediate step. Leave its T3 project alone until the second move.
3. Clone the workspace repository at the workspace path.
4. Move each checkout in, one journal each.
5. Create the workspace's T3 project at the folder, or reuse a workspace project already rooted there. Never turn a checkout's own project into it: its root-bound threads would resume in the workspace folder. Re-root each checkout's project to its new path, check it, and archive it. Never delete one.
6. Trust each checkout's `mise` config and run the continuation test in each.

To move a checkout out, move it, verify it, then remove it from the workspace's `.gitignore`, guidance, and setup steps. Rollback refuses once the workspace stops ignoring the old path. To relocate a workspace, clone it at the new path, move each checkout in, and retire the old clone under the usual rules once it holds nothing unpushed.

## Recovery

```sh
python3 scripts/migrate.py verify --journal /private/evidence/move.json
python3 scripts/migrate.py rollback --journal /private/evidence/move.json
```

Rollback moves the checkout back only while the saved Git state still matches, ignoring just the pointers this move changed, and before any provider work resumes. It refuses later edits, new refs, config changes, an occupied old path, and active cwd processes, and it can finish an interrupted move or rollback. Once checkpoints are recorded it refuses outright, since threads have new history. From then on the journal is evidence, and reversing the move means a new move with its own journal and T3 checks. Inspect any failure; never delete paths, prune, reset refs, or add a compatibility symlink.

If the T3 update or continuation fails, keep threads idle, roll back Git if eligible, restore the project's saved root and title, and confirm the threads work. Read the project before retrying an ambiguous API call. Either side failing to restore is an incomplete migration.

## Evidence and tests

Fixture tests live in the dotfiles repository, not the deployed skill: run `python3 -m unittest tests.skills.test_repo_workspace_migrate` from `git -C "$(chezmoi source-path)" rev-parse --show-toplevel`. They use disposable repositories and cover the real rename and repair, failure and recovery, workspace moves including the creation sequence above, and checkpoint recording.

Live moves on macOS, Linux (btrfs), and Windows (Microsoft's VFS Git) kept every ref, stash, and thread, including dirty checkouts with up to 41 changes and one with more than 70 retained worktrees, and their threads continued afterwards. On 2026-11-21 the Ritornel checkouts moved into a new workspace on all three, before the helper accepted workspace destinations, so the `git check-ignore` route is so far proven by fixtures only. Unborn, nested, submodule, and cross-filesystem moves are untested here; pilot before expanding into them.
