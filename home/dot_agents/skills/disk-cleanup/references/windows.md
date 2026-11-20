# Windows: not implemented

There is no validated Windows workflow or measurement helper. Nothing in this file has been tested. Don't describe Windows figures as validated measurements, and don't assume APFS behavior applies.

Missing compared with macOS:

- A read-only helper that measures unique physical footprint, including ReFS block clones and NTFS hard links, and reports gaps instead of zeros.
- Accounting for Volume Shadow Copies and System Restore points.
- Fixture validation for sparse files, NTFS compression, block cloning on Dev Drive (ReFS), hard links, and unreadable files.

Until then, use the shared principles in `SKILL.md` with a coarse inventory. Explorer's "Size on disk" and `gdu -x` report allocated totals, in which shared data counts more than once. Record the volume's free space before and after cleanup, and label every figure with its method.

Untested leads for a future implementation: `fsutil file queryallocranges`, `fsutil sparse queryrange`, `compact /q`, `vssadmin list shadowstorage`, and `Dism /Online /Cleanup-Image /AnalyzeComponentStore`.
