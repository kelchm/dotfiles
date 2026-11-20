# macOS (APFS)

Validated on macOS 26 with APFS, on fixture files and an isolated disk image. Contents: tools, workflow, reading `scan` output, APFS behavior, preservation checks, cleanup commands, snapshots and backups, after cleanup.

## Tools

- **`scripts/apfs-measure.py`** (this skill) is read-only and needs only Python 3.9+, so `/usr/bin/python3` works. `volume` reports container free space, macOS availability estimates, and snapshots. `scan` measures candidates exactly. It never writes, flushes, or deletes files, and never downloads iCloud placeholders.
- **`gdu-go`** (Homebrew `gdu`, renamed to avoid GNU `gdu`) gives a fast coarse inventory: `gdu-go -n -p -x -o <record>.json <root>`. Its `dsize` sums per-file allocation, so clones count in full every time. Without it, `du -xk -d 2 <root>` has the same meaning.
- **`diskutil`** inventories containers, volumes, and snapshots. The helper wraps the parts it needs.
- **`tmutil`** shows backup state read-only: `listlocalsnapshots /`, `latestbackup`, `destinationinfo`, `isexcluded <path>`.
- **Disk Utility** (View > Show APFS Snapshots) shows snapshot sizes. No command-line tool reports snapshot-retained bytes. If a decision depends on them, ask the user to read them there. Don't install commercial snapshot tools unless the user asks.

## Workflow

1. **Volume context.** Run `python3 <skill>/scripts/apfs-measure.py volume` and save the output. When `container_free_bytes` is far below `important_use_available_bytes`, snapshots or purgeable data hold the difference. That is a separate decision (see [Snapshots and backups](#snapshots-and-backups)), and the difference is not their measured size.
2. **Coarse inventory.** Run `gdu-go -x` over likely roots: home, the development root, agent and T3 data (`~/.t3`, `~/.claude`, `~/.codex`), `~/Library/Caches`, `~/.cache`, package stores, and VM storage. Directories that need Full Disk Access (Mail, Messages, Photos libraries) can fail. Record such failures as unknown, not small.
3. **Attribute.** Map large entries to projects and purposes. Signals include the path (development root alias, T3 worktree path), `git -C <dir> rev-parse --show-toplevel`, `git check-ignore -q <path>`, marker files beside the directory (`Cargo.toml` with `target/`, `package.json` with `node_modules/`, `go.mod`, `.venv`), cache owners (`~/Library/Caches/<bundle id>`), and VM images (`Docker.raw`, OrbStack and Colima disks, `.utm` bundles).
4. **Measure candidates** with `apfs-measure.py scan <candidate>... --reference <root>...` before stating any saving. References are roots that might share blocks with the candidates: sibling worktrees and the primary checkout for build output, the package store for `node_modules` (`pnpm store path`), and the source for anything copied with `cp -c` or Finder's Duplicate. A reference may contain candidates. No other roots may overlap. A scan processes roughly 5,000 files a second, so measure targeted trees rather than whole disks, and run large scans in the background with output to a file.
5. **Check, authorize, clean.** Run the [preservation checks](#preservation-checks), confirm the scope is authorized, and use the owning tool's [cleanup command](#cleanup-commands).
6. **Verify.** See [After cleanup](#after-cleanup).

## Reading `scan` output

Each candidate, the `combined` set of all candidates, and each reference report:

| Field | Meaning |
|---|---|
| `logical_bytes` | Data and resource fork lengths. Compressed files count their uncompressed length. |
| `allocated_bytes` | Sum of `st_blocks` over distinct inodes: the allocated total. |
| `unique_physical_bytes` | Union of the device ranges holding data forks, resource forks, and compressed streams. Holes are excluded and shared blocks count once. |
| `private_bytes_sum` | Sum of `ATTR_CMNEXT_PRIVATESIZE`, which Apple defines as bytes "not trapped inside a clone or snapshot, and which would be freed immediately if the file were deleted". It covers data forks only. |
| `shared_with_references_bytes` | Candidate blocks that a reference also holds. References report the same overlap as `shared_with_candidates_bytes`. |
| `exclusive_within_coverage_bytes` | Candidate blocks that no other scanned file references. Snapshots and unscanned files are ignored. |
| `retained_elsewhere_bytes` | A lower bound on candidate data held by unscanned files or snapshots: data-fork blocks that APFS reports as shared but that no scanned file explains. |
| `reclaim_if_deleted_bytes.at_least` | Private bytes of files whose every hard link is inside the candidate. Deleting the candidate frees these immediately. |
| `reclaim_if_deleted_bytes.at_most` | Exclusive minus retained bytes, plus the allocation of files that could not be mapped: an upper bound on freed file data, given current snapshots. |
| `shared_between_candidates_bytes` | In `combined` only: blocks that several candidates share. |
| `complete`, `gaps` | Measures that are incomplete, with reasons, counts, affected allocation, and sample paths. |
| `counts` | Files, directories, hard links, links outside the roots, compression, resource forks, dataless, and purgeable files. |

Interpretation:

- Report reclaim as a range. When the bounds are close, the figure is solid. A wide range usually means clones shared among the candidate's own files, which a snapshot may also hold.
- When `at_least` is far below `allocated_bytes` and `retained_elsewhere_bytes` is large, snapshots or clones outside the candidate hold the data. Deleting frees little now. Snapshot-held space returns as the snapshots expire.
- Deleting related clones together frees more than the sum of their individual figures. Use `combined` for a batch.
- Gaps and what they mean:
  - `open_failed:EPERM` or `EACCES`: privacy protection or permissions. Grant the terminal Full Disk Access or leave it unmeasured.
  - `unreadable_directory`: the subtree is unmeasured.
  - `other_filesystem`: a mount inside the candidate. Deleting the candidate would cross into it.
  - `dataless`, `dataless_directory`: iCloud placeholders with data not on disk. The helper does not open them.
  - `unallocated_range`: data written so recently that it has no blocks yet. Measure again later.
  - `changed_during_scan`: something is writing. This is also a preservation signal.
  - `private_excludes_resource_fork`: private size covers data forks only, so `private_bytes_sum` and `at_least` exclude these files' resource and compressed data.
- `compressed_in_metadata_files` counts files whose compressed data sits inline in filesystem metadata. Metadata is not measured.
- Not measured: filesystem metadata, extended attributes other than resource forks (reported as logical `xattr_bytes`), and snapshot space held by files already deleted.

## APFS behavior that changes the answer

- **Clones** share blocks until either copy is modified. `cp -c`, Finder's Duplicate, pnpm (clone import by default), Bun (`clonefile` backend), and uv (`clone` link mode on macOS) all create them. Allocated totals count every clone in full.
- **Hard links** keep data until the last link goes. `files_with_links_outside_roots` counts files that something outside the scanned roots keeps alive.
- **Sparse files**: VM and container disk images report huge logical sizes, and only their allocation is stored. Space freed inside a guest returns to macOS only after the guest trims or the manager compacts the image. Compare the image's allocated size before and after.
- **Compression**: system files and many app bundles are transparently compressed, so their logical size exceeds their allocation.
- **Snapshots**: Time Machine local snapshots (`com.apple.TimeMachine.*.local`) and OS update snapshots (`com.apple.os.update-*`). Deleting a file that a snapshot references frees nothing until that snapshot is gone. macOS removes purgeable Time Machine snapshots after about a day, or sooner under space pressure. The important-use estimate already counts them as available.
- **Purgeable files** count toward availability estimates but not toward free space.
- `/Users` is a firmlink into the Data volume. The sealed system volume is never a cleanup target.

## Preservation checks

- **Open files**: `lsof -nP +D <dir>` for small trees. For large ones, run `lsof -nP -Fn 2>/dev/null | grep -F 'n<dir>/'`.
- **Processes**: `pgrep -lf <tool-or-path>`, and the VM or container manager's own list or status command.
- **Recent writes**: `find <dir> -mmin -120 -print -quit`.
- **Git**, run against the repository that contains the path:
  - `git check-ignore -q <path>` succeeds only for ignored paths, such as build output.
  - `git status --porcelain --untracked-files=all` lists uncommitted and untracked work.
  - `git log --branches --not --remotes --oneline` lists unpushed commits.
  - `git stash list` and `git worktree list` show other local work.
- **Kept-data fingerprint**: `find <dir> -type f -print0 | xargs -0 stat -f '%N%t%z%t%m' | LC_ALL=C sort | shasum -a 256`, plus a file count.

## Cleanup commands

Run a preview first where one exists, and keep the command's output in the action record.

| Owner | Preview or inventory | Cleanup |
|---|---|---|
| Homebrew | `brew cleanup --dry-run` | `brew cleanup`. Add `--prune=all` only if clearing every cached download is authorized. |
| pnpm | `pnpm store path` | `pnpm store prune` removes packages no project references. |
| Bun | | `bun pm cache rm` |
| uv | `uv cache dir` | `uv cache prune` (unused entries) or `uv cache clean` (everything) |
| Go | `go env GOCACHE GOMODCACHE` | `go clean -cache`, `go clean -modcache`. For a project-local module cache, set `GOMODCACHE=<dir>`. Module files are read-only, so use this rather than `rm`. |
| Rust | | `cargo clean` in the project removes `target/`. |
| mise | `mise prune --dry-run` | `mise prune` removes unused tool versions. `mise cache clear` clears mise's cache. |
| Xcode | | `xcrun simctl delete unavailable`. Remove `~/Library/Developer/Xcode/DerivedData` only while Xcode is closed. |
| Docker and other VMs | `docker system df` | `docker builder prune`, `docker image prune`. These free space inside the VM disk first. Then confirm that the image's allocation shrank. |

Caches without an owning command, such as an application's folder under `~/Library/Caches`, can be removed directly once the application is closed and the scope is authorized.

## Snapshots and backups

- List snapshots with `apfs-measure.py volume`, or with `tmutil listlocalsnapshots /`.
- No command reports how much a snapshot retains. Never derive it from the important-use estimate minus free space.
- Deleting a local snapshot is a separate, explicit decision. Before proposing it, confirm a recent backup on another disk with `tmutil latestbackup`. Delete only the named snapshot dates with `tmutil deletelocalsnapshots <date>`. Never pass a mount point, which deletes every local snapshot on the volume, and never delete `com.apple.os.update-*` snapshots.
- Backup exclusions (`tmutil addexclusion`) change what is protected, so adding one is also a separate decision. Report candidates with `tmutil isexcluded`.

## After cleanup

- Run `volume` again. Report the change in `container_free_bytes` beside the removed allocation and the reclaim bounds. Name concurrent activity such as builds, VMs, and backups. If a Time Machine snapshot predates the deletion, explain that the space returns when it expires.
- Repeat the kept-data fingerprints and confirm they match.
- Save the action record: authorization, items with project, purpose, and class, preservation evidence, commands with exit codes and log paths, volume context before and after, and the observed change.
