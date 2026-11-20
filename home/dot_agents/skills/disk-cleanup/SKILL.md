---
name: disk-cleanup
description: Find what is using disk space on the user's machine, measure what deleting it would actually free, and carry out scoped cleanup of authorized, reproducible data. Use when asked why a disk is full, what uses space, how much could be freed, or to clear caches and build output. Retiring checkouts and worktrees belongs to repo-workspace.
---

# Disk cleanup

Understand storage before removing anything: what uses it, for which project and purpose, how much deletion would actually return, and whether it can be recreated. Remove only what the user authorized, preferably with the owning tool, and verify the result.

## Platform

Read the reference for the machine's operating system before measuring:

- **macOS**: [references/macos.md](references/macos.md). Validated on APFS, with a read-only measurement helper.
- **Linux**: [references/linux.md](references/linux.md). Not implemented.
- **Windows**: [references/windows.md](references/windows.md). Not implemented.

Without a validated workflow, a coarse inventory is still useful. Label every figure with how it was measured, and never present it as the space that deletion would free.

## Measurement terms

Each measure answers a different question. Keep them distinct in notes, records, and reports.

- **Logical size**: the length a reader sees. Sparse files and compression make it exceed storage.
- **Allocated total**: the sum of each file's allocated blocks, as `du` and most disk-usage tools report. Blocks shared by clones, hard links, or deduplicated stores count once per file, so totals overstate storage.
- **Unique physical footprint**: the distinct blocks a set of files occupies, with shared blocks counted once.
- **Private bytes**: per file, the bytes no other file or snapshot references. Their sum is the least that deleting all the files frees. It is not the joint saving when the files share blocks with each other.
- **Exclusive within coverage**: blocks that no other scanned file references. It speaks only for the roots actually scanned; unscanned files or snapshots may still hold the data.
- **Snapshot-retained bytes**: data that deletion cannot free while snapshots or restore points still reference it.
- **Available estimate**: the operating system's estimate of space it could make available, including purgeable data and expiring snapshots. It is neither free space nor a measure of any of the above.
- **Free space and observed change**: the volume's actual free space, and its change across a cleanup. On a live machine the change includes other writers and snapshot activity, so report it beside what was removed, never as its size.

A missing, unreadable, unsupported, or unmeasured value is unknown, not zero. State the coverage behind every claim of exclusivity or savings.

## Attribute before cleaning

Attribute storage to the project and purpose that produced it, such as "Rust build output in four of one project's worktrees" or "a research prototype's Go module cache", rather than generic buckets like "Developer" or "Caches". Then classify each candidate:

- **Reproducible**: package-manager caches and stores, build output, downloaded toolchains. Usually removable after preservation checks, preferably with the owning tool's cleanup command.
- **Unique or costly to recreate**: research data and evidence, downloaded models and datasets, generated reports. Inspect and report; remove only with specific authorization.
- **VM and container disks**: filesystems with their own state. Reclaim space from inside them or with their manager, and never delete an image because it is large.
- **Git and local work**: source, uncommitted and untracked changes, unpushed branches, stashes, worktrees. Build output inside a checkout is reproducible; the checkout itself is not. Retiring a checkout or worktree is a repo-workspace decision.
- **Conversation and agent history**: session logs and transcripts. Keep them unless the user explicitly asks otherwise.
- **Restore points**: snapshots and backups. Always a separate decision.

## Preservation and authorization

- Authorization covers what the user named: specific paths, kinds of data, or tools. Within that scope, proceed without asking again. Before widening destructive scope, present the new candidates with their measurements and ask.
- Immediately before removing a candidate, check its current state in proportion to its risk: recent writes, processes or open files using it, and, for anything inside a repository, whether the path is ignored build output and whether uncommitted, untracked, unpushed, or stashed work is nearby. A package cache needs less checking than a directory beside source.
- Snapshot deletion, backup exclusions or retention changes, and checkout or worktree retirement are separate decisions. Never fold them into a cache cleanup, even when they would free the most space.
- Prefer the owning tool's cleanup command, which respects its locks and indexes, over deleting its files. Never delete through symlinks or across mount points.
- When cleaning near data that must stay, fingerprint the kept data before and after (file count and a hash of paths, sizes, and modification times) and confirm it is unchanged.

## Records

Save small dated JSON records of each measurement and action: scope, roots, method and tool version, coverage and gaps, values, commands with exit codes, and free space before and after. Keep them in the task's output directory or wherever the user keeps them. Earlier records show growth and suggest where to look, but re-measure before acting: an old scan is not current.

## Report

Lead with what changed or what the user needs to decide. For each item, give the project and purpose, the measure used and its coverage, what was done, and what remains. Report the observed free-space change separately from the amount removed, with its snapshot and background-activity context. List remaining decisions, such as snapshots, backups, VM disks, unique data, and checkouts, with the evidence each needs.
