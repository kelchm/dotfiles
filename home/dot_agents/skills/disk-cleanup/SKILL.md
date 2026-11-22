---
name: disk-cleanup
description: Find what occupies disk space, estimate what could be reclaimed, and clean up authorized reproducible data. For retiring repositories or worktrees, use repo-workspace.
---

# Disk cleanup

Explain where the space went, what could be freed and how confident the estimate is, then clean up only what the user authorizes. Read the guide for the platform first: [macOS (APFS)](references/macos.md), [Linux](references/linux.md), or [Windows](references/windows.md). [Common causes](references/common-causes.md) lists what has taken the most space in practice, with each owner's cleanup command.

## Measuring

- **Start at the volume or pool.** Its free space is the number cleanup changes. Several mounts, subvolumes or APFS volumes can share one pool, so group them before adding anything up.
- **Check snapshots early.** Local snapshots (Time Machine, Btrfs, ZFS) keep deleted data, so cleanup can free almost nothing until they go. List them before estimating, and when free space doesn't move after cleanup, recommend thinning or deleting specific snapshots for the user to approve.
- **Name the size you report.** *Logical* is file length. *Allocated* is the blocks charged to each file. *Physical* is the blocks actually in use after counting clones, reflinks and hard links once. Discovery tools report logical or allocated sizes, and a sum of them can count the same blocks more than once.
- **Use cheap tools to find leads and strong tools to confirm them.** `du`, Storage settings and similar inventories rank directories quickly. Use the stronger measurement in the platform guide only on the largest leads.
- **Partial coverage is a finding.** Keep permission errors, skipped mounts and unreadable entries in the report. Leave an estimate unknown when the evidence cannot support a number.
- **Measuring must not change state.** Don't download cloud placeholders, start stopped VMs or containers, or elevate privileges just to measure.

## Workflow

1. **Audit.** Record volume usage, the user's free-space target or chosen stopping point, rank the top-level directories, and drill into the largest ones. Attribute each lead to its owner: a project, application, package manager, VM or service. Include data worth keeping so the user sees the whole picture.
2. **Recommend.** For each actionable lead, give the owner's cleanup command, the estimated savings and how they were measured, what is lost (rebuild or redownload cost, history, local work), and the risk. Separate reproducible caches and build output from leads that need a decision (VMs, snapshots, old projects, unique data). Stop recommending further removals once the chosen target is met.
3. **Act on what the user authorized.** Approval covers the batch the user approved; a later run needs its own. Prefer the owner's command, previewed first (for example `brew cleanup --dry-run`), and refresh previews before acting. Before deleting a directory, check for open files and running jobs. For build output inside Git, confirm the exact path is ignored and holds no tracked or local work. Snapshot deletion, backup exclusions and VM retirement each need their own explicit approval. Repositories and worktrees go through `repo-workspace`.
4. **Verify.** Remeasure the same volume or pool. Report unique live data removed (when measurable; otherwise report unknown), observed pool free-space gain, and estimated snapshot-held data (inferred from any shortfall and snapshot checks) separately, and explain any shortfall. Common causes are snapshots, open handles, hard links or clones kept elsewhere, and guest disk images that need trim or compaction. When something keeps growing back, such as a build cache or a model store, propose a cap, quota or exclusion instead of repeated cleanup, and verify prevention at the ordinary entry point (effective settings plus a small representative build or write) rather than trusting configuration files alone.

Report sizes in bytes or binary units (GiB, MiB) and say which. When a later comparison would help, keep a dated note of what was measured, the commands used and the gaps.
