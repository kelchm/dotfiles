---
name: repo-workspace
description: Decide where a repository checkout lives (Personal, Contribute, or Reference, alone or inside a workspace folder), how contribution remotes, forks, and worktrees are set up, and whether it gets a T3 project; audit, move, or retire checkouts without losing work or T3 history. Use before cloning or forking a repository, creating or renaming a T3 project, starting or publishing upstream contribution work, or moving, reorganizing, or cleaning up checkouts and worktrees. Ordinary work in an established checkout does not need it.
---

# Repository workspaces

Repository identity, the local path and alias, remote forks, and T3 projects and their history are separate decisions. Changing or retiring one never implies the same for the others. `scripts/audit.py` inventories checkouts read-only. `scripts/migrate.py` moves one checkout that a user explicitly authorized. Neither one changes T3 state.

## Where a checkout lives

Choose a category by what the work is for, not by GitHub ownership or fork status:

- **Personal**: projects the user directs. This includes owned products, infrastructure and configuration, prototypes, experiments, private research, and intentionally maintained downstream variants, even when they are technically GitHub forks.
- **Contribute**: retained checkouts for work aimed at an upstream the user does not direct, including recurring contribution or debugging. The user's publishing fork does not make it Personal.
- **Reference**: retained, independent source or build references. Clones used for a single task and fixtures go in that task's scratch directory instead.

Layout:

- The path is `<development root>/<category>/<alias>`. Reuse the machine's established development root (for example `~/Development`) and never rename it. Category folders are `Personal`, `Contribute`, and `Reference` on macOS and Windows, and `personal`, `contribute`, and `reference` on Linux. If a machine has no established root yet, ask before creating one.
- The alias is a recognizable project name. Keep established aliases and their case. Do not add host, owner, vendor, or topic levels.
- Before placing anything, read the task's intent, the repository's history and remotes, any existing project, and the current work. Keep an established intentional placement. If the long-term role is still materially unclear, ask one small concrete question about intent before creating a lasting home. Meanwhile, investigate read-only or work in task scratch.
- A directory with the same name is a conflict to resolve, not a duplicate to replace. Verify which variant it is, and choose a distinct meaningful alias if both are needed.
- Placement is stable. An occasional upstream PR from a Personal downstream stays in Personal, and an experiment in a contribution checkout does not move it. Deliberately adopting a separately maintained variant can prompt an explicit reorganization plan.
- The development root and category folders are plain directories. They are never Git repositories or T3 projects. Before registering a Git checkout, confirm that `git rev-parse --show-toplevel` equals its real path.
- **Workspaces.** Several repositories that make up one project and are regularly worked on together can share a workspace folder at `<category>/<alias>`. The folder is a checkout of a small repository that holds only guidance (`AGENTS.md`, `README.md`, `.gitignore`), and each repository is its own checkout inside it at `<workspace>/<alias>`, ignored by the workspace's `.gitignore`. This is the only place a checkout sits inside another. A repository worked on alone stays a plain checkout. A workspace's README gives a fresh machine's setup steps, and each checkout inside needs its own `mise trust`, since trust is per path. For example, `Personal/ritornel` is `ritornel/workspace`, with `ritornel/ritornel` at `Personal/ritornel/ritornel` and `ritornel/lab` at `Personal/ritornel/lab`.
- The chezmoi-managed dotfiles stay where chezmoi manages them. `chezmoi source-path` can be a subdirectory, so the Git and T3 root is `git -C "$(chezmoi source-path)" rev-parse --show-toplevel`. Never create a duplicate checkout under Personal.

## Remotes and publication

- **Contribute**: `origin` is the user's publishing fork. `upstream` is the verified contribution target, with pushes disabled. The baseline branch tracks the target's actual branch on `upstream`. Topics start from freshly fetched `upstream/<target>` without tracking it. The user's own long-lived branches, such as deploy branches, can live on the fork and track `origin`; the baseline only mirrors upstream. For settings, worktree creation, and the first publication, read [references/contribution.md](references/contribution.md).
- **Personal**: `origin` is the maintained repository, and the baseline tracks its maintained line. An `upstream` remote for the ancestral project is optional. Never point a downstream's maintained branch at `upstream` just because GitHub calls it a fork.
- Verify a contribution target against GitHub's fork-parent metadata and the task. A configured `upstream` remote is evidence, not proof.
- Forking is normal once contribution publication is authorized. Local-only, no-fork, and no-push instructions mean no fork, push, or PR. Setup, a project title, or a directory never grants publication authority.
- When setting up a GitHub fork or looking into its workflow runs, follow the [fork Actions guidance](references/contribution.md#github-actions-on-forks).

## T3 projects

- Register a checkout when independent resumption would be useful, when repository-bound native controls are needed, or when returning to this repository is credibly likely. Cloning, forking, or using it as a dependency is not enough on its own. State the reason in a sentence when you register it.
- Title a contribution project with the verified upstream `owner/repo` (for example `siderolabs/talos`), whatever the local alias or fork is called. Title a Personal project with a recognizable name and no prefix.
- Reuse existing projects and keep their IDs, history, icons, scripts, and settings. Don't create projects per branch, worktree, PR, or fork. Pass `workspaceRoot` explicitly, and don't start a new top-level thread unless asked.
- Planning can stay in an existing parent conversation, but source work runs in the repository it changes. An attachment from another project doesn't show that repository's Git state.
- A workspace gets one project, rooted at the workspace folder. T3 discovers the checkouts inside it as tracked folders, so they get no projects of their own. When a repository joins a workspace, re-root its existing project to the checkout's new path and archive it; never delete it, since its threads stay readable and resumable there. Don't reuse a repository's project as the workspace's, because its root-bound threads would move to the workspace folder.
- Let T3 and other agent hosts create and manage the worktrees they own. Name any manual worktree meaningfully and uniquely under an existing worktree area.

## Audit, move, and retire

- Live T3 tools are authoritative. Native project thread listings return active threads only, so for archived and deleted threads bound to a checkout or worktree, use the `t3-thread-search` skill's `--path` lookup. Never write to or copy T3's database or provider session files.
- Give `audit.py` explicit roots: the development root, T3's worktree and scratch directories, other agent hosts' worktree directories, and the dotfiles Git root. Missing roots, Git errors, and scan limits are findings, not evidence that something is disposable.
- Never delete, archive, prune, merge, or move automatically because a task finished, a PR merged, a checkout is clean or old, or a thread was archived. Broad planning does not authorize every move in the plan.
- Retire only the specific checkout or worktree the user authorized. Collect fresh evidence immediately before acting: active runs, open PRs, tracked, untracked, and ignored files, local-only refs, stashes, detached commits, submodules, and other tools using the path. Retire task worktrees before their primary clone. Repair or preserve broken Git links; never prune them.
- Deleting a T3 project deletes its threads. Keep projects that hold history unless that specific loss is authorized.
- Updating a project root alone does not fix worktree pointers or thread bindings. For an authorized move, including into, out of, or creating a workspace, read [references/migration.md](references/migration.md) first. For examples of placement and registration decisions, see [references/cases.md](references/cases.md).
