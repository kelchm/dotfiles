# Linux

## Identify the storage layer

Start at the path that is running out of room. On Linux with GNU coreutils and util-linux:

```sh
findmnt -T "$path" -o TARGET,SOURCE,FSTYPE,FSROOT,OPTIONS
lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS
df -B1 -P -- "$path"
df -i -- "$path"
```

`df` reports filesystem space. Quotas can constrain the caller further. Check inode pressure where the filesystem reports useful inode counts. On minimal systems use `df -Pk` and `/proc/self/mountinfo`. Group mounts of the same filesystem or pool rather than adding their totals. For Btrfs, group subvolumes by filesystem UUID and read `btrfs filesystem usage --raw "$path"` for pool usage and estimated free. For ZFS use `zpool list -p` and `zfs list -p -o space` to separate pool from dataset and snapshot accounting. For thin LVM use `lvs -o lv_name,lv_size,pool_lv,data_percent,metadata_percent` where accessible. Identify guest, container and network filesystems before attributing their space to the host.

## Rank and attribute

Inspect mounts below the chosen root first. `du -x` stays on its starting device and can still enter same-device bind mounts. Scan each intended view once and exclude nested mounts or snapshot trees from the live inventory. Keep output, errors and exit status:

```sh
du -a -P -x -B1 -d1 -- "$root" > inventory.tsv 2> inventory-errors.log
status=$?
sort -nr inventory.tsv | head -n 25
```

`-d1` limits the output depth and still walks the tree. The root row includes its children. If only portable flags are available, use `du -axk` on smaller scopes and report KiB. Keep partial results labeled, including zero rows for inaccessible paths. Drill into the largest leads in home, workspaces, `/var`, application data and temporary directories. Attribute each to a project, package manager, service or application. `journalctl --disk-usage` can explain journal storage and `docker system df -v` can break down the current Docker context. Check access and confirm that context before using its figures.

`du` reports inode allocation and normally counts a hard-linked inode once per invocation. `du --apparent-size` reports logical size, useful for identifying sparse images. Rows can share reflinked storage. Give the byte measure and scan scope, and keep clone-inflated totals out of physical footprint and reclaim claims. [GNU `du` manual](https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html)

## Verify footprint and reclaim

- **Hard links:** for a specific deletion set, inspect `stat -c '%d:%i links=%h length=%s blocks=%b block_bytes=%B %n' -- <paths>`. Compare the number of distinct links being removed with the inode link count. On Btrfs identify the inode by filesystem UUID, subvolume ID and inode number, and avoid counting bind aliases as extra links. A surviving link keeps its file data.
- **Shared extents:** `filefrag -v -b1` can diagnose sparse and reflinked extents on supported local filesystems. For mapped file data, union valid, unencoded ranges within the same filesystem only. Skip unknown, delayed, inline or otherwise unmappable ranges and label the result partial. Btrfs addresses are filesystem logical addresses. `btrfs filesystem du --raw -s <paths>` reports sharing for each argument using FIEMAP file-side lengths. Compressed extent lengths cannot establish physical bytes. Keep any reported bounds confined to the bytes actually mapped. [FIEMAP flags](https://docs.kernel.org/filesystems/fiemap.html) · [Btrfs usage and sharing](https://btrfs.readthedocs.io/en/stable/btrfs-filesystem.html)
- **Retention:** use the snapshot manager to list snapshots and report their size where supported. For example, use `btrfs subvolume list -s` or ZFS `usedbysnapshots`. Permission errors and missing counters mean unknown. A gap between `df` and the file inventory can be snapshots, filesystem overhead, inaccessible trees or deleted files still held open. Check `lsof +L1` where available and visible to the caller.

Use the owning tool's preview or exact deletion list. Give a reclaim estimate only for the supported, measured scope and explain hard links, snapshots, shared data and open handles that could keep it. Report unknown when the evidence is insufficient. After authorized cleanup, repeat `df` on the same filesystem. For guests or thin storage, remeasure the relevant backing allocation too.
