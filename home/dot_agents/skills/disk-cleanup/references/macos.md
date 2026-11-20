# macOS (APFS)

APFS clones share blocks between files, and all volumes in a container share its free space. Summed per-file allocation from `du`, Finder or `gdu` can count cloned data more than once. `scripts/apfs-measure.py` reads block maps to count each block once. It runs with `/usr/bin/python3` or any Python 3.9+, is read-only, never downloads cloud placeholders, and stays on the starting volume.

Keep its JSON in a fresh directory so later runs don't overwrite earlier evidence:

```sh
out=$(mktemp -d "${TMPDIR:-/tmp}/disk-audit.XXXXXX")
helper="$skill_dir/scripts/apfs-measure.py"  # this skill's directory
```

## 1. Find the volume

```sh
python3 "$helper" volume "$target" > "$out/volume-before.json"
```

Pass a path on the volume you are cleaning (`/System/Volumes/Data` for the startup disk). Report these separately:

- `container_free_bytes`: free space shared by every volume in the container. Cleanup changes this.
- `container_volumes[].used_bytes`: usage per volume, including system, VM and backup volumes.
- `important_use_available_bytes`: capacity macOS considers available for important writes. It is free space plus whatever purgeable data macOS could evict, so it is never an amount that cleanup will free.
- `snapshots`: local snapshots and whether they are purgeable. The space a snapshot retains is not reported here. Use Disk Utility or a dedicated tool for that. Don't infer it from available minus free.

## 2. Rank directories

```sh
du -xk -d 1 /System/Volumes/Data 2> "$out/du-errors.log" | sort -nr | head -25
```

Drill into the largest children, usually the home directory, workspaces, `/private/var` and `/Library`. These are allocation totals, good for finding leads but inflated by clones. If you use `gdu`, check its JSON `read_error` flags even when it exits 0.

## 3. Measure the largest leads

```sh
python3 "$helper" footprint ~/Library ~/Development ~/.cache > "$out/footprint.json"
```

Pass disjoint roots in one call. Each row's `mapped_file_data_bytes` counts each block once within that root. `combined` counts each block once across all of them, and `shared_between_roots_bytes` shows the overlap. Rows with `complete: false` list their `gaps` and are only lower bounds. The walk excludes filesystem metadata, extended attributes other than resource forks, and blocks held only by snapshots.

## 4. Estimate a specific deletion

```sh
python3 "$helper" scan <candidate>... --reference <kept-root>... > "$out/scan.json"
```

Add a `--reference` for each place that likely holds clone partners you will keep, such as sibling worktrees or a package store. A reference may contain the candidates, and its walk skips them. Read `combined` for a batch.

| Field | Meaning |
|---|---|
| `reclaim_if_deleted_bytes` | `at_least` / `at_most` range for file data freed by deleting the candidates. `null` means unknown. This is the number to report. |
| `unique_physical_bytes` | Blocks used by the candidates, each counted once. |
| `allocated_bytes` | Sum of per-file allocation, as `du` would count it. |
| `shared_with_references_bytes` | Blocks the candidates share with the reference roots, which stay after deletion. |
| `retained_elsewhere_bytes` | Blocks held by something unscanned: a clone outside the references or a snapshot. |
| `complete`, `gaps` | Which figures are exact and why the others are not. |

A hard link outside the candidates keeps its data, and the helper counts that. Snapshots can still hold deleted blocks, so the observed gain may be smaller than estimated until they expire.

## Common large owners

- **VMs and containers:** Docker Desktop, Colima, OrbStack, UTM and Parallels keep large disk images. Match each image to a registered machine (`colima list`, `docker context ls`) and, for a running engine, inspect `docker system df -v`. Guest cleanup frees host space only after the guest trims or the image is compacted. Remeasure the image afterward.
- **Package and toolchain caches:** Homebrew, mise, pnpm, npm, Cargo, Go, Xcode `DerivedData` and simulators. Use the owner's preview, such as `brew cleanup --dry-run` or `mise prune --dry-run`. For pnpm, `pnpm store path` (or a project's `node_modules/.modules.yaml`) locates the store.
- **Build output:** `target/`, `node_modules/`, `.build/`, `dist/`. Confirm with `git check-ignore` and `git ls-files` on the exact path. Use scoped commands such as `cargo clean --target-dir <dir>`. Check `lsof -nP +D <dir>` on small trees.
- **Snapshots and backups:** `tmutil listlocalsnapshots /`. Check `tmutil latestbackup` before deleting a local snapshot, and `tmutil isexcluded <path>` when deciding whether data is backed up.

## After cleanup

Rerun `volume` on the same path and compare `container_free_bytes`. If less space returned than estimated, check snapshots, open handles (`lsof +L1`) and guest images.
