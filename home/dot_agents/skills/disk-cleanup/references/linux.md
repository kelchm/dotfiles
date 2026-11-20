# Linux: not implemented

There is no validated Linux workflow or measurement helper. Nothing in this file has been tested. Don't describe Linux figures as validated measurements, and don't assume APFS behavior applies.

Missing compared with macOS:

- A read-only helper that measures unique physical footprint and blocks shared with other files, and reports gaps instead of zeros.
- Snapshot accounting for whichever layer the machine uses, such as Btrfs, ZFS, or LVM thin snapshots, each with different semantics.
- Fixture validation for reflinks (Btrfs, XFS), hard links, sparse files, filesystem compression, and unreadable files.

Until then, use the shared principles in `SKILL.md` with a coarse inventory. `du -xk` or `gdu -x` (`gdu-go` under Homebrew) report allocated totals, in which reflinked data counts more than once. Record `df` output before and after cleanup, and label every figure with its method.

Untested leads for a future implementation: `gdu --exclusive-size` (reflink-aware on Linux), FIEMAP through `filefrag -v`, `btrfs filesystem du`, `compsize`, and `zfs list -o space`.
