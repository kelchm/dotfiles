# Linux

Commands assume GNU coreutils and util-linux. On minimal systems, use `df -Pk`, `du -xk` and `/proc/self/mountinfo`, and report KiB.

## 1. Find the filesystem

```sh
findmnt -T "$path" -o TARGET,SOURCE,FSTYPE,FSROOT,OPTIONS
lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS
df -B1 -P -- "$path"
df -i -- "$path"
```

- Several mounts can share one filesystem or pool, such as bind mounts, Btrfs subvolumes and ZFS datasets. Group them by source or UUID before adding totals.
- Full inodes look like a full disk. Check `df -i` where the filesystem reports meaningful counts. Btrfs and ZFS do not.
- **Btrfs:** `btrfs filesystem usage --raw "$path"` shows allocation by profile and estimated free space.
- **ZFS:** `zpool list -p` for the pool and `zfs list -p -o space` for each dataset, split into live data, snapshots and children.
- **Thin LVM:** `lvs -o lv_name,lv_size,pool_lv,data_percent,metadata_percent`.
- User and project quotas can block writes while `df` still shows free space.
- Identify container, guest and network filesystems before charging their space to the host.

## 2. Rank directories

Write the output to a fresh directory, and keep errors and the exit status:

```sh
out=$(mktemp -d "${TMPDIR:-/tmp}/disk-audit.XXXXXX")
du -a -P -x -B1 -d1 -- "$root" > "$out/inventory.tsv" 2> "$out/errors.log"
echo "exit $?" >> "$out/errors.log"
sort -nr "$out/inventory.tsv" | head -25
```

- `-x` stays on one filesystem but still enters bind mounts of the same filesystem. Check `findmnt -rn -o TARGET,SOURCE | awk -v r="${root%/}/" 'index($1"/", r) == 1'` first for mounts at or below the root.
- `-d1` limits output, not the walk. The root row includes everything below it.
- `du` reports allocation and counts each hard-linked inode once per run. `--apparent-size` reports logical size. A large gap between the two points to sparse files or compression.
- Inaccessible directories show up in `errors.log` and are missing from the totals. Report the result as partial.

Drill into the largest children, usually `/home`, workspaces, `/var` (logs, containers, package caches), `/opt` and `/tmp`. Useful owner reports:

- `journalctl --disk-usage` for the systemd journal.
- `docker system df -v` or `podman system df -v` for the current engine and context.
- `snap list --all` shows disabled revisions kept on disk. `flatpak uninstall --unused` lists unused runtimes and asks before it removes anything.
- `~/.cache`, language toolchains (`~/.cargo`, `~/go`, `~/.local/share/mise`) and IDE caches.

## 3. Check what keeps data after deletion

- **Hard links:** `stat -c '%h %i %n' -- <paths>`. If the inode's link count is higher than the number of links you are deleting, the data stays.
- **Reflinks (Btrfs, XFS):** `du` counts shared extents in full for each file. `btrfs filesystem du -s --raw <paths>` splits each argument into exclusive and shared bytes. It counts compressed extents at their uncompressed length, so use `compsize` for on-disk size of compressed data. `filefrag -v` shows the extents of a single file.
- **Snapshots:** `btrfs subvolume list -s "$path"`, or ZFS `usedbysnapshots` from `zfs list -o space`. Deleting a file that a snapshot still holds frees nothing until the snapshot goes.
- **Deleted but still open:** `lsof +L1` lists unlinked files that a process still holds open. The space returns when the process closes them or restarts.

If `df` shows much more used space than the inventory found, the difference is usually snapshots, inaccessible trees, deleted-but-open files or filesystem overhead. Name which ones you checked.

## 4. After cleanup

Rerun `df` (and `btrfs filesystem usage` or `zpool list` where relevant) on the same filesystem. For a guest or thin-provisioned volume, also remeasure the backing image or pool on the host. It shrinks only after trim or compaction.

References: [GNU du](https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html) · [Btrfs filesystem](https://btrfs.readthedocs.io/en/stable/btrfs-filesystem.html) · [FIEMAP](https://docs.kernel.org/filesystems/fiemap.html)
