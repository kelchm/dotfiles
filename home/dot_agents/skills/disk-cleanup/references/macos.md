# macOS (APFS)

Use `/usr/bin/python3` or Python 3.9+ with `scripts/apfs-measure.py` from this skill. The helper is read-only. It disables dataless file materialization, stays within each root's volume and skips symlinks below the roots.

## Answer “what is using space?”

1. Run `apfs-measure.py volume /System/Volumes/Data` (or pass the path in question). Read `container_free_bytes`, `container_size_bytes` and `container_volumes[].used_bytes` from `diskutil`. APFS volumes share container free space. The important and opportunistic availability estimates are separate OS estimates. Snapshot names and purgeable flags establish their presence, not their retained bytes. `CapacityInUse` for the Data volume includes data the live file walk cannot see.
2. Discover large paths with `/usr/bin/du -xk -d 1 <root>`, extending by a level only where it helps attribution. Keep stderr even with usable stdout. `gdu-go -n -p -x --no-prefix --depth 1 --log-file <log> <root>` is another option. Inspect the log or JSON `read_error` flags even on exit 0. On startup volumes cover Data, then drill into home, app/container state, project workspaces, VM disks and package data as warranted. The discovery bytes count APFS clones repeatedly. Use the paths as inputs to step 3.
3. Run `apfs-measure.py footprint <root> ...` on the largest plausible contributors, including ones to preserve. Use disjoint paths in a single invocation for a combined figure. Split generic directories by project or application. For example, measure the music working directory and VM storage directly before reporting how much space they occupy. When measuring a project's children instead, pass the children together and use `combined` for their union. Never add the rows, including rows from separate runs.
4. Report `mapped_file_data_bytes` for measured roots. The command sorts complete measurements first and ranks by mapped bytes within each group. When `complete` is false, report only the mapped portion with its gaps, or report the full size as unknown. `allocation_without_map_bytes` is a per-inode discrepancy within the scanned files, may include shared blocks, and cannot be added to the footprint. There may also be entirely inaccessible files. The combined footprint covers the selected roots, excludes filesystem metadata, and is not a partition of the Data volume.

Typical invocation, with output retained as evidence:

```sh
/usr/bin/python3 "$skill/scripts/apfs-measure.py" volume /System/Volumes/Data > volume.json
/usr/bin/python3 "$skill/scripts/apfs-measure.py" footprint "$media" "$vm_storage" "$project" > footprint.json
```

Avoid a full extent walk of millions of files when named roots answer the question. Start a costly root separately if necessary and name it as pending or unmeasured until it returns. If headline sizes are unavailable, report container figures and the paths to investigate without attaching discovery sizes to the usage breakdown.

## Answer “how much would this action free?”

Use `scan <candidate> ... [--reference <root>]` once you have a concrete deletion set. Optional repeatable references expose sharing with specific data that will stay, such as a sibling checkout or a package store. A reference can contain candidates, which the helper excludes from that reference's walk. Compare `combined` for a batch, where clones or hard links across candidates may change the result.

- `allocated_bytes` is summed `st_blocks` over distinct inodes. Clones count repeatedly. `unique_physical_bytes` is the mapped block union used by `footprint`.
- `exclusive_within_coverage_bytes` is mapped data held entirely by the deletion set among scanned files, subject to inode link counts. This includes clones shared within the set. Snapshots and unscanned clones can still retain blocks.
- `reclaim_if_deleted_bytes` is a file-data estimate for unlinking the measured set. Its lower estimate uses APFS private data-fork sizes where every inode link is in scope. The upper estimate accounts for known sharing and private-size evidence of retention. It is unknown if reclaim coverage is incomplete. Null endpoints are unknown. A zero estimate applies to the measured action and current retention, and can change after snapshots expire or sharing changes. It does not estimate VM guest cleanup or compaction.
- Resource forks and compressed streams are mapped where possible. APFS private size covers the data fork, excludes those streams, and is not a joint saving for a set of clones. The helper checks allocated bytes against mapped bytes per inode, probes stable preallocated tails beyond EOF, and flags unexplained differences. It excludes detected changing files' extents and suppresses inconsistent estimates. Concurrent changes can still make a live scan stale.
- The walk does not measure filesystem metadata, ordinary xattr physical storage, or blocks held only by snapshots. `retained_elsewhere_bytes` cannot distinguish unscanned file references from snapshots. Review `complete` and `gaps` for the measure you use.

## Follow the biggest actionable leads

- **VM and container storage:** map sparse images on the host, then inventory by profile and match disks to the manager's inventory (for example, `colima list`, `limactl disk list` with the right `LIMA_HOME`, or the installed manager's equivalent). An unlisted disk is a lead to reconcile with old profiles and project history. For a running Docker context check `docker system df -v` and builder-specific usage. A stopped guest needs a separate start decision before guest measurements. Use scoped cleanup within the guest, then the supported trim or compaction path, and remeasure host allocation.
- **Package stores:** resolve the manager/version in a consuming project. For pnpm, project `node_modules/.modules.yaml` can reveal the store path even when a global shim fails. Inspect store versions and live project references before proposing cleanup. Installed tools or runtimes may still be selected by project config. Example previews include `brew cleanup --dry-run` and `mise prune --dry-run`. Read the applicable tool's help before choosing a command.
- **Build outputs:** identify the project and build configuration first. Check `git check-ignore`, `git ls-files` through the exact target, current build processes and recent writes. Use the owning command with an explicit scope (for example `cargo clean --target-dir <dir>` or Go cache cleanup with the intended `GOCACHE` or `GOMODCACHE`). Prefer `lsof -nP +D <dir>` for small candidates and process-level checks for large trees.
- **Research, working libraries, model weights and agent history:** identify the actual project or application and what can be regenerated. A directory under `.cache` can contain unique evidence. Report meaningful usage even when preservation is the correct decision.
- **Snapshots and backups:** `diskutil apfs listSnapshots` and `tmutil listlocalsnapshots` inventory restore points. Use Disk Utility's APFS snapshot view for its size fields, or an available dedicated tool. Check what the size field measures. Never derive retained bytes from available minus free or from the difference between Data volume usage and a file inventory. A snapshot request needs exact scope and current `tmutil latestbackup` context. To audit backup coverage, use `tmutil isexcluded <path>`. Adding exclusions changes protection and is a separate decision.

After an authorized action, record `volume` again. Use container free-space change to describe observed recovery. Check the VM image again after trim, or retained files near the cleanup where relevant. Large allocation removed with little free-space change is evidence to investigate retention, open handles and guest-to-host reclamation.
