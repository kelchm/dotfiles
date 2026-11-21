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

For the bytes that deleting a file would free, macOS reports a per-file *private size*: data shared with no clone or snapshot. gdu's `--exclusive-size` reports it on macOS in releases after 5.39.0:

```sh
mise x aqua:dundee/gdu@<version> -- gdu --exclusive-size --non-interactive <candidate>
```

Summing private sizes undercounts when the candidate holds several clones of the same file, since none of them is private. Files compressed by APFS report their full allocation instead. Treat the result as a lower bound on what the deletion frees.

For reproducible data such as caches and build output, the free-space change after deletion is the most reliable measurement. For data that cannot be recreated, the decision is whether to keep it, and a byte estimate rarely changes that.

## Common large owners

- **VMs and containers:** Docker Desktop, Colima, OrbStack, UTM and Parallels keep large disk images. Match each image to a registered machine (`colima list`, `docker context ls`) and, for a running engine, inspect `docker system df -v`. Guest cleanup frees host space only after the guest trims (for Colima, `colima ssh -- sudo fstrim -av`) or the image is compacted. Remeasure the image afterward.
- **Package and toolchain caches:** Homebrew, mise, pnpm, npm, Cargo, Go, Xcode `DerivedData` and simulators. Use the owner's preview, such as `brew cleanup --dry-run` or `mise prune --dry-run`. For pnpm, `pnpm store path` (or a project's `node_modules/.modules.yaml`) locates the store.
- **Build output:** `target/`, `node_modules/`, `.build/`, `dist/`. Confirm with `git check-ignore` and `git ls-files` on the exact path. Use scoped commands such as `cargo clean --target-dir <dir>`. Check `lsof -nP +D <dir>` on small trees.
- **Snapshots and backups:** Check `tmutil latestbackup` before deleting a local snapshot, and `tmutil isexcluded <path>` when deciding whether data is backed up.

## After cleanup

Rerun `diskutil info` on the same path and compare *Container Free Space*. If less space returned than expected, the usual causes are clones of the deleted data kept elsewhere, snapshots, files still held open (`lsof +L1`), and guest images that have not been trimmed or compacted.
