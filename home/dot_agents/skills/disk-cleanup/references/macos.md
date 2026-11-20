# macOS (APFS)

Run `scripts/apfs-measure.py` from the skill with `/usr/bin/python3` or Python 3.9+. The helper reads metadata, skips descendant symlinks and other mounts, and disables cloud placeholder downloads.

## Audit

1. Run `apfs-measure.py volume /System/Volumes/Data`. Report container free space, volume usage and macOS availability estimates separately. APFS volumes share container free space. Snapshot flags show which restore points exist and whether they are purgeable. Snapshot-retained bytes require a separate measurement.
2. Use `du -xk -d 1 <root>` starting at `/System/Volumes/Data`, then drill into large roots such as home, workspace storage and `/private/tmp`. Keep stderr. For `gdu-go`, check its log or JSON `read_error` flags even on exit 0. Use allocation totals to select paths for measurement. APFS clones can inflate those totals.
3. Run `apfs-measure.py footprint <root> ...` on the largest leads. Pass disjoint roots together and read `combined` for their block union. Report `mapped_file_data_bytes` with the scope and any `gaps`. A row with `complete: false` is only a partial measurement. Avoid a full extent walk when bounded roots answer the question. Report unmeasured paths without promoting discovery totals into physical sizes.

The file walk excludes filesystem metadata, ordinary extended attributes and blocks held only by snapshots. `allocation_without_map_bytes` describes a mapping discrepancy that can include shared blocks. Keep it out of physical totals.

## Estimate a specific deletion

Run `apfs-measure.py scan <candidate> ... [--reference <root>]`. Repeat `--reference` for likely clone partners that will stay, such as sibling worktrees or a package store. A reference may contain candidates, which its walk skips. Use `combined` for a batch.

- `allocated_bytes` sums per-inode allocation. `unique_physical_bytes` measures the block union. `exclusive_within_coverage_bytes` is mapped data held entirely by the deletion set among scanned files, subject to hard links. `retained_elsewhere_bytes` cannot distinguish unscanned files from snapshots.
- `reclaim_if_deleted_bytes` estimates file data released by unlinking the set. Private sizes cover the data fork only. The upper estimate accounts for known sharing and retention. Check `complete` and `gaps`. A null endpoint is unknown, and a zero estimate can change with retention. Guest trim needs its own measurement.

## Follow the largest actionable leads

- **VMs and containers:** match host disk images to registered profiles (for example, `colima list`). Trace unlisted disks to their original work. For a running Docker context, use `docker system df -v` and builder usage. Starting a stopped guest changes state. After authorized guest cleanup and supported trim or compaction, remeasure host allocation.
- **Package stores:** resolve the manager version from a consuming project. pnpm's `node_modules/.modules.yaml` can identify the store when its shim fails. Check live project references and store versions. Use scoped previews such as `brew cleanup --dry-run` or `mise prune --dry-run`.
- **Build output:** check `git check-ignore` and `git ls-files` on the exact target. Use explicit scope, such as `cargo clean --target-dir <dir>` or the intended Go cache variables. Use `lsof -nP +D <dir>` for small trees and process checks for large ones.
- **Snapshots and backups:** use Disk Utility's snapshot size fields or a dedicated tool when retention size matters. The availability gap and the difference between volume usage and live files do not measure it. Before deleting named local snapshots, check `tmutil latestbackup`. Audit backup coverage with `tmutil isexcluded <path>`.

After cleanup, rerun `volume`. If actual recovery is below expectations, check snapshots, open handles and guest trim.
