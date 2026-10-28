---
name: repo-workspace
description: Decide where repository checkouts live, how contribution forks and remotes are set up, and when a repository gets its own T3 project; audit, move, or retire checkouts without losing work or T3 history. Use before cloning or forking a repository, creating or deleting a T3 project, or moving, reorganizing, or cleaning up checkouts and worktrees. Ordinary work in an established checkout does not need it.
---

# Repository workspaces

Repository identity, local checkouts, remote forks, and T3 projects with their history are separate things. Creating or retiring one never implies the same for the others. `scripts/audit.py` inventories checkouts read-only. `scripts/migrate.py` moves one checkout that a user explicitly authorized. Neither one changes T3 state.

## Identity and layout

- Before creating a checkout, look for an existing one by verified identity (host, owner, repo, plus fork and upstream aliases), not by directory name. For a contribution, verify the target from GitHub's fork-parent metadata and the task. A configured `upstream` remote is evidence, not proof.
- GitHub checkouts live at `~/Development/<owner>/<repo>`, named for the contribution target even when the fork is renamed. The user's own repositories use `kelchm`. Managed stores, such as the chezmoi source, and deliberately independent downstream forks keep their established paths and roles. Compare GitHub names case-insensitively, but keep the provider's spelling.
- Keep one clone per working repository, with `origin` as the user's fork and `upstream` as the contribution target. A second clone needs a stated isolation, version, or fixture purpose. Reference clones and fixtures go in the current task's scratch directory.
- The convention does not authorize moving an established checkout. Never overwrite an occupied destination or a case collision. Resolve the conflict instead.
- Owner directories and `~/Development` itself must not be Git repositories. Before registering a checkout, confirm that `git rev-parse --show-toplevel` equals its real path. An ancestor repository does not count.

## Contribution setup

- Fork when publication is authorized, without asking again for confirmation. Keep any task restrictions, such as local-only work or no fork yet. Without a fork, clone with `--origin upstream`, disable its push URL, and add `origin` once forking is authorized.
- Set `remote.pushDefault=origin`, disable pushes to `upstream`, and track upstream's default branch. Discover that branch rather than assuming `main`. Check the existing settings first, and keep deliberate downstream or per-branch choices.
- T3's `newWorktreesStartFromOrigin` can start a contribution worktree from the fork. Fetch `upstream` and pass an explicit upstream ref with `startFromOrigin:false` instead of changing the environment default.
- Let T3 or the agent host create the worktrees it owns. Manual worktrees go under `~/Development/_worktrees/<owner>/<repo>/<task>`.

## T3 projects

- Reuse a project matched by real path or verified identity, and keep its ID and history.
- Create a project when the repository becomes an independent workstream: the main thing being edited, built, and tested, with its own thread, worktree, or PR follow-up. A one-off contribution can qualify. Cloning, forking, reading a dependency, or using a fixture does not.
- Create one project per working repository, not one per fork, branch, PR, or worktree. A change belongs to the repository being edited, even when another project motivated it.
- Pass `workspaceRoot` explicitly to `t3_project_create`. After an ambiguous result, re-read the project list before retrying. A new project does not authorize publishing or a new top-level thread. If the work is already underway under another project, continue there with an explicit cwd, and recommend the new project for the next workstream.

## Audit, move, and retire

- Live T3 tools are authoritative for projects and threads. Never write to or copy T3's database or provider session files. Before passing `--t3-db` to `audit.py`, confirm that it is the live environment's active database, because legacy and current databases can coexist.
- Give `audit.py` explicit roots. These are typically `~/Development`, `~/.t3/worktrees`, `~/.t3/scratch`, other agent hosts' worktree directories, and `chezmoi source-path`. The script also follows registered worktrees outside those roots. Compare every live project root against the results. Missing roots, Git errors, and scan limits are findings, not evidence that a workspace is disposable.
- Retire only the specific checkout or worktree the user authorized. Collect fresh evidence immediately before acting: active runs, open PRs, tracked, untracked, and ignored files, local-only refs, stashes, detached commits, submodules, and other tools using the path. A clean status, an old date, an archived thread, or a merged PR is not enough on its own. Retire task worktrees before their primary clone.
- A broken Git link needs recovery or a plan to preserve it, not pruning. Treat a `prunable` flag as something to investigate. Backups, submodule Git directories, and managed stores are not duplicates.
- Deleting a T3 project deletes its threads. Keep projects that hold history, and settle or archive their threads instead, unless that specific loss is authorized.
- Updating a project root alone does not fix worktree pointers or thread bindings. For an authorized move, read [references/migration.md](references/migration.md) first.
