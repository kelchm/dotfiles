---
name: disk-cleanup
description: Assess disk pressure, identify what actually occupies storage, and carry out authorized cleanup of reproducible data. Use for disk usage, reclaim estimates, and clearing caches or build output. For retiring repositories or worktrees, use repo-workspace.
---

# Disk cleanup

Pick the workflow for the question. An audit should explain the largest measured consumers and what the user can do about them. A cleanup should verify the specific action, run it within the authorized scope, and measure the result.

Platform references: [macOS (APFS)](references/macos.md) · [Linux (stub)](references/linux.md) · [Windows (stub)](references/windows.md).

## Audit

1. Start with filesystem or storage-pool free and used space. Record availability estimates and snapshot or restore-point context separately.
2. Use a cheap directory inventory to find leads. Verify the biggest leads with the platform's physical measurement before putting numbers next to them in a usage report. Prioritize the large roots even when they contain data to keep. A clone-inflated allocation sum is unsuitable for the headline, the breakdown, and any estimate of savings.
3. Attribute the measured roots by owner, project and purpose. Report the largest verified consumers, what could be cleaned, and the largest relevant areas left unmeasured. Treat partial results as partial. Rows can share physical blocks even when paths are disjoint, so use a jointly measured union for a total. Explain any gap from the pool's used space as unaccounted for unless separately measured.
4. For cleanup advice, follow the largest actionable leads to their owner: build output to the project, package data to the package manager and its consumers, images to the VM/container manager, and snapshots to the backup tool. Give a concrete next action or the specific evidence still needed for each worthwhile item. If only trivial savings are available in the scanned subset, say what larger areas were checked and where larger savings remain plausible.

## Cleanup

- Scope follows the user’s authorization. Before acting, check recent writes, open files and running jobs as appropriate. For build output in a checkout, identify the build root, check ignored status and confirm the removal contains no tracked files or local work. A cache path alone does not establish reproducibility.
- Prefer the owner's scoped preview and cleanup commands. For a VM, distinguish guest reclaim and host image allocation, and verify both when possible. Protect unique data, conversation history and evidence. Snapshot deletion, backup exclusions, VM retirement and checkout or worktree retirement are separate decisions.
- Verify the same pool’s free space before and after. Report what was removed and observed free-space change as separate measures. Account for concurrent writes, delays and snapshots. Keep a small dated record of measured roots, method, gaps, commands and results when it helps future comparison.
