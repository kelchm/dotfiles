---
name: disk-cleanup
description: Find what occupies disk space, estimate what could be reclaimed, and clean up authorized reproducible data. For retiring repositories or worktrees, use repo-workspace.
---

# Disk cleanup

Read the reference for [macOS (APFS)](references/macos.md), [Linux](references/linux.md), or [Windows](references/windows.md).

1. **Audit.** Start with free and used space at the relevant volume or pool. Use a cheap inventory to find leads, then verify the largest roots with the strongest measurement the filesystem supports. Include data worth keeping and attribute results by project, application and purpose. Label logical size, allocation and mapped file data separately. Use a measured union for totals that may share blocks, and explain the largest gaps in coverage.
2. **Decide.** Follow large cleanup leads to the owning tool. Give the user a concrete action with its measured or unknown savings and the evidence needed to proceed. Protect unique data, agent history and local work. Snapshot deletion, backup exclusions, VM retirement and checkout retirement each need their own scope.
3. **Act and verify.** Check recent writes, open files and running jobs as appropriate. For build output in Git, verify the exact path is ignored and contains no tracked or local work to preserve. Prefer the owner's scoped preview and cleanup command within the user's authorization. Compare the same pool's free space before and after, and report the observed change separately from the data removed. Keep a dated record of scope, measurements, gaps and commands when it helps future comparison.
