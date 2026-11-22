# macOS (APFS)

APFS volumes in one container share its free space, and APFS clones share blocks between files. `du`, Finder's Get Info and most disk-map apps charge every clone its full size. Package managers clone on macOS (pnpm, bun and uv by default), and so do Finder copies, `cp -c` and Xcode simulators. A `node_modules` or virtualenv that `du` reports at several GB can therefore free almost nothing when deleted.

## 1. Find the volume

```sh
diskutil info "$target" | grep -E 'Container (Total|Free) Space|Volume Used Space|APFS Container'
diskutil apfs list            # every volume in the container and its usage
tmutil listlocalsnapshots /   # local snapshots
```

Pass a path on the volume you are cleaning (`/` for the startup disk). *Container Free Space* is the number cleanup changes. Finder's "available" figure includes purgeable data macOS can evict on its own, so it is not free space and not something cleanup frees. The space a snapshot retains is not reported by these commands. Use Disk Utility's snapshot list for it, and don't infer it from available minus free.

## 2. Rank directories

```sh
out=$(mktemp -d "${TMPDIR:-/tmp}/disk-audit.XXXXXX")
du -xk -d 1 /System/Volumes/Data 2> "$out/du-errors.log" | sort -nr | head -25
```

Drill into the largest children, usually the home directory, workspaces, `/private/var` and `/Library`. These totals are fine for finding leads but inflated by clones.

## 3. Count clones once

[dua-cli](https://github.com/Byron/dua-cli) 3.0.3+ counts fully shared clones once with `--deduplicate-apfs-clones`. Run it without installing anything globally:

```sh
dua() { mise x aqua:Byron/dua-cli@3.0.3 -- dua "$@"; }
dua aggregate -x --deduplicate-apfs-clones ~/Library ~/Development ~/.cache
```

- Within one run, each clone family is charged to a single path, and the total is their real combined footprint. A large drop compared with `du` means the lead is mostly clones.
- It does not let you choose which path a clone family is charged to. A small result for one directory does not prove that deleting it frees that amount.
- A clone that has since been modified counts in full again, so partially shared files are still overstated.

## 4. Estimate a specific deletion

For regular uncompressed files, macOS reports a per-file *private size* (`ATTR_CMNEXT_PRIVATESIZE`): data-fork bytes not shared with any clone or snapshot. gdu's `--exclusive-size` queries it on macOS in releases after `5.39.0` (`5.39.0` does not include macOS support yet):

```sh
mise x aqua:dundee/gdu@<version> -- gdu --exclusive-size --non-interactive <candidate>
```

Until a `gdu` release with macOS `--exclusive-size` ships (or when private size is otherwise unavailable), leave the per-deletion reclaim estimate unknown and rely on `dua --deduplicate-apfs-clones` for combined footprint or the post-deletion free-space change for reproducible data.

Summed private sizes are a defensible lower bound **only** for verified unshared, uncompressed file data whose hard links all disappear in the deletion set:

- **Hard links:** a link outside the deletion set keeps the file's data alive even when its private size is nonzero; check link counts (`stat -f '%l %i %N'`) when external links are possible.
- **Compressed files (`UF_COMPRESSED` / `decmpfs`):** APFS stores compressed data outside the data fork and reports private size `0`, so tools like `gdu --exclusive-size` fall back to reporting the file's full allocated size. That can overcount compressed files that are cloned or retained by a snapshot. The same fallback occurs when private size cannot be read.
- **Internal clones:** if the deletion set holds every clone of a file (with no clone or snapshot outside it), summing private sizes undercounts those bytes because none of the clones is private on its own.

Report those gaps (compressed files, external hard links, unreadable entries, or unverified clone groups) as uncertain rather than presenting a raw total as a guaranteed minimum. Keep advanced extent mapping optional and use it only when a high-stakes decision requires tighter bounds.

For reproducible data such as caches and build output, the observed container free-space change after deletion is the most reliable measurement. For data that cannot be recreated, the decision is whether to keep it, and a byte estimate rarely changes that.

## Common large owners

- **VMs and containers:** Docker Desktop, Colima, OrbStack, UTM and Parallels keep large disk images. Match each image to a registered machine (`colima list`, `docker context ls`) and record its current power state. For a running engine, inspect `docker system df -v` and follow the scoped image-removal rules in [Common causes](common-causes.md#vms-and-containers) rather than blanket image pruning. Guest cleanup frees host space only after trimming the verified guest data mount (for example, check mounts in `colima ssh` with `findmnt` / `df -h`, then run `colima ssh -- sudo fstrim -v <mount>`) or compacting the image. If a stopped VM was started solely for authorized cleanup and trim, restore its prior stopped state afterward, and remeasure both host disk image allocation and container free space.
- **Package and toolchain caches:** Homebrew, mise, pnpm, npm, Cargo, Go, Xcode `DerivedData` and simulators. Use the owner's preview, such as `brew cleanup --dry-run`. Treat `mise prune --dry-run` / `mise ls --prunable` as a candidate list, cross-check retained-project pins and external tool defaults (such as `rustup`), refresh the preview before acting, and uninstall exact vetted versions (see [Common causes](common-causes.md#package-and-toolchain-caches)). For pnpm, `pnpm store path` (or a project's `node_modules/.modules.yaml`) locates the store.
- **Build output:** `target/`, `node_modules/`, `.build/`, `dist/`. Confirm with `git check-ignore` and `git ls-files` on the exact path. Use scoped commands such as `cargo clean --target-dir <dir>`. Check `lsof -nP +D <dir>` on small trees.

## Snapshots, backups, and prevention

Before deleting any local APFS snapshot, verify backup state and scope the exact volume and snapshot:

```sh
tmutil status                                  # confirm Running = 0 (no active backup)
tmutil latestbackup                            # confirm latest completed backup (may require root/Full Disk Access)
diskutil apfs list                             # identify the Data volume (e.g. disk3s5 / /System/Volumes/Data)
diskutil apfs listSnapshots /System/Volumes/Data
tmutil listlocalsnapshots /
```

If `tmutil latestbackup` cannot be read due to permissions, check Time Machine settings with the user and treat backup recency as unknown until confirmed.

With explicit approval naming the volume and snapshot UUID, remove only the approved snapshot where supported:

```sh
sudo diskutil apfs deleteSnapshot <volume> -uuid <uuid> -wait
```

`-wait` waits for space reclamation to complete before returning. Contrast this with `tmutil deletelocalsnapshots <date>` (which deletes matching-date snapshots on every mounted disk) and `tmutil deletelocalsnapshots <mount_point>` (which deletes all local snapshots on that disk).

- **Shared snapshot blocks:** multiple snapshots can reference the same deleted blocks, so removing one snapshot may free little until every snapshot pinning those blocks is gone.
- **Thinning by amount:** `tmutil thinlocalsnapshots / <bytes> <urgency 1-4>` works without `sudo`, but stops once macOS considers the requested floor met—so it can satisfy the target while leaving the largest retaining snapshot in place.
- **Exclusions vs. quotas:** `tmutil isexcluded <path>` checks backup exclusion. A path-level exclusion (`tmutil addexclusion <path>` sticky, or `-p <path>` fixed-path) omits the path from future Time Machine backups, **not** from local APFS snapshots on that volume—deleted blocks under an excluded path can still be pinned by local snapshots. A volume-wide exclusion (`tmutil addexclusion -v <volume>`) excludes an entire separate volume from Time Machine, but APFS volumes in the same container still share pool capacity unless bounded with a hard volume quota (`diskutil apfs addVolume ... -quota <size>`).

## After cleanup

Rerun `diskutil info` on the same path and compare *Container Free Space*. Report unique live data removed, observed container free-space gain, and estimated snapshot-held data separately. If less space returned than expected, the usual causes are snapshots (including shared blocks across multiple snapshots), clones or hard links kept elsewhere, files still held open (`lsof +L1`), and guest images that have not been trimmed or compacted.
