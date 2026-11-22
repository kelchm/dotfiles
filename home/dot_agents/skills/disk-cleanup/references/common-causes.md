# Common causes

These came up repeatedly in real cleanups. Each entry says how to spot the cause, the owner's preview and cleanup commands, and what went wrong in practice. Preview first and get approval for each batch. When the same cause keeps growing back, also propose a way to cap it.

## Space that doesn't come back

Check these first when a cleanup frees less than expected. They were the largest single effect in practice.

- **Local snapshots (macOS):** Time Machine keeps local APFS snapshots, and deleted files stay pinned in them. In one cleanup, about 380 GiB of deleted build output freed almost nothing until two old snapshots were removed, raising free space from 92 to 416 GiB. Before removing snapshots, verify no backup is running (`tmutil status`) and check the latest completed backup (`tmutil latestbackup`), scope the exact APFS volume (`diskutil apfs list`, `diskutil apfs listSnapshots <volume>`), and get explicit approval for each snapshot. Where supported, remove the exact approved snapshot with `sudo diskutil apfs deleteSnapshot <volume> -uuid <uuid> -wait` rather than broader `tmutil deletelocalsnapshots` scopes. Multiple snapshots can share the same deleted blocks, and `tmutil thinlocalsnapshots / <bytes> <urgency 1-4>` can satisfy a requested floor while leaving the largest retaining snapshot in place. A reboot does not reliably clear them. See the [macOS guide](macos.md#snapshots-backups-and-prevention).
- **Btrfs and ZFS snapshots** behave the same way. See the Linux guide.
- **Clones and hard links:** `du` overstated real use by 2× to 50× on cloned trees. Examples: a media library and its imported copy, browser code-signing clones, and staging directories that tool updaters left behind. On macOS, count clones once before ranking (see the macOS guide).
- **VM and container disk images** don't shrink when the guest deletes data. The guest must trim the verified data mount before host space returns.
- **Files still open** after deletion: `lsof +L1`.

## VMs and containers

- **Docker build cache** is usually the largest reclaimable item inside a Docker VM (Colima, Lima, Docker Desktop, OrbStack). It showed up as tens of GiB per builder. Inspect it with `docker system df -v` for the daemon's own builder, and list other builders with `docker buildx ls` and `docker buildx du --builder <name>`. Use `docker builder prune --all` (or `docker buildx prune --builder <name> --all`) for reproducible build cache.
- **Scoped Docker image removal (no blanket `docker image prune --all`):** inspect images first (`docker image ls --digests`, `docker image inspect <id>`). Remove specific images with `docker image rm <image-id-or-ref>` only when backed by evidence of recovery:
  - a **pullable immutable digest** verified in its registry (for example `docker buildx imagetools inspect <repo@sha256:...>`);
  - a **checksum-verified archive** for that exact image (for example `docker image save -o <archive.tar> <ref>` verified against its digest/checksum and exact image ID); or
  - a **complete rebuild recipe and inputs** (Dockerfile, build context, pinned base/dependencies, and build arguments still present).
  Preserve containers, volumes, and any image with unresolved provenance unless explicitly approved as a retention decision.
- **Trim the verified guest data mount and restore VM state:** record the VM's prior power state first (`colima list`, `limactl list`). Inside the guest, verify which mount backs the container data (e.g. `findmnt` / `df -h` in `colima ssh`) and trim that mount (`colima ssh [--profile <name>] -- sudo fstrim -v <mount>`). Without trimming, the host disk image keeps its allocation. If a stopped VM was started for authorized cleanup, restore its prior stopped state afterward, and measure **both** host disk image allocation (allocated blocks on the host image file) **and** storage-pool free space.
- **It grows back.** One builder reached 60 GiB again within a week. Propose a cap: `builder.gc` in `daemon.json` for the default `docker` driver, the builder's BuildKit configuration for `docker-container` builders, or a scheduled prune.
- **Stale VMs:** more disk images than registered machines (`colima list`, `limactl list`) is common. A disk with no registered machine is not automatically disposable, so trace it to its project first. Retire a known-unneeded VM through its tool, such as `colima delete <profile> --data`.

## Build output

- **Multiplied across worktrees.** Rust `target/`, `.zig-cache/`, `node_modules/` and similar output exist once per working copy. Agent worktrees and review scratch copies multiply them quickly: one cleanup found 94 Rust `target` directories and 39 Zig caches. Find them with `find <root> -type d \( -name target -o -name .zig-cache -o -name node_modules \) -prune`, nested ones included. Then confirm each is ignored (`git check-ignore`), check that no build is running, and look for hand-written files that ended up inside one.
- **Cleanup:** prefer the toolchain's command (`cargo clean`) or delete the verified directory. Deleting the build output of a retired worktree is usually the biggest safe win. Use `repo-workspace` to retire the worktree itself.
- **Prevention:** remove build output when a worktree is retired, and keep scratch builds out of long-lived directories.
- **Small `/tmp` (Linux):** a RAM-disk `/tmp` (tmpfs, often with a size limit or quota) runs out of space quickly during large builds and fails with `ENOSPC` or `EDQUOT`. Check `findmnt -T /tmp` and point build output at the real disk, for example with `CARGO_TARGET_DIR`.

## Package and toolchain caches

Mostly reproducible, but each has its own cleanup command, and some remove more than a cache:

| Owner | Inspect / preview | Clean |
|---|---|---|
| Homebrew | `brew cleanup --dry-run` | `brew cleanup` (add `--prune=all` for every cached download) |
| mise | `mise prune --dry-run` / `mise ls --prunable` (candidate list), `du -sh "$(mise cache path)"` | `mise uninstall <tool@version> ...` (exact vetted versions); `mise cache prune` or `mise cache clear` for downloads |
| uv | `du -sh "$(uv cache dir)"` | `uv cache prune` (dangling entries and cached environments, which uv recreates), `uv cache clean` |
| pnpm | `pnpm store path` | `pnpm store prune` |
| npm | `du -sh ~/.npm/_cacache` | `npm cache clean --force` |
| Go | `go env GOCACHE GOMODCACHE` | `go clean -cache`; `-modcache` also deletes downloaded modules |
| Nix | `nix-store --gc --print-dead` | `nix-store --gc`. `nix-collect-garbage -d` also deletes old generations, which removes rollback points. |
| Xcode | `~/Library/Developer/Xcode/DerivedData` | delete DerivedData |
| Xcode simulators | `xcrun simctl list devices unavailable` | `xcrun simctl delete unavailable` deletes those devices with their apps and data, so it needs a decision |
| pacman | `paccache -d -k2` | `paccache -r -k2` |
| systemd journal | `journalctl --disk-usage` | `journalctl --vacuum-size=<size>` permanently deletes archived logs and leaves active files, so it is a retention decision |

A cache's size is not what its cleanup frees: prune commands keep what is still in use. Report the preview's number, not the directory size.

**Vetting `mise` candidates:** treat `mise prune --dry-run` / `mise ls --prunable` as a candidate list drawn only from configs `mise` has loaded (`tracked-configs`), tool stubs it has run (`tracked-stubs`), and observable running processes. Before removing anything, cross-check candidates against retained-project version files (`mise.toml`, `.tool-versions`, `rust-toolchain.toml`) and defaults owned by external toolchain managers (such as `rustup`'s default channel via `rustup toolchain list` / `rustup show`). Refresh the preview right before acting and remove exact vetted versions with `mise uninstall <tool@version>` rather than blanket `mise prune`. In practice, both the default Rust channel and retained-worktree pins have appeared in a real preview, and exact selection avoided removing them.

## Prevention and caps

When a cache, build store, or VM keeps growing back, verify any preventive measure at the **ordinary entry point**—not just by reading a config file:

- Check the effective settings as the normal shell or command sees them (for example `command -v <tool>`, tool config/status output, and environment variables).
- Run a small representative build or write to confirm outputs actually go through the configured cache or target path instead of bypassing it.

Distinguish the four common space controls because they behave differently:

- **Periodic collection budget:** a soft logical or size/age limit enforced by a tool's garbage collector (such as build-cache GC); active builds can temporarily exceed it between sweeps.
- **Volume quota:** a hard ceiling enforced by the filesystem on a volume or subtree (for example APFS `diskutil apfs addVolume ... -quota <size>` or Linux project/user quotas); writes fail with `ENOSPC`/`EDQUOT` at the limit.
- **Path-level backup exclusion:** omits a file or directory from future backups (`tmutil addexclusion <path>` sticky or `-p <path>` fixed-path on macOS), **not** from local APFS snapshots—blocks deleted under an excluded path can still stay pinned in local snapshots.
- **Volume-wide exclusion:** excludes an entire separate volume from backups (`tmutil addexclusion -v <volume>` on macOS); however, APFS volumes in one container still share pool capacity, so unbounded growth on an excluded volume still reduces free space for the whole container unless capped by a quota.

## AI models

Local model stores often hold hundreds of GiB, frequently across several apps: Hugging Face (`~/.cache/huggingface`), Ollama (`ollama list`), LM Studio (`lms ls`) and app-specific caches.

- `hf cache prune --dry-run` finds detached revisions and incomplete downloads. In practice that was about 30 GB.
- Different quantizations or variants of one model are deliberate choices, not duplicates. A matching name and size does not prove two files are identical, so compare hashes before calling something a duplicate.
- Treat models as needing a decision. They are reproducible but can be large and slow to download again, and some have been removed upstream.

## Application data

- **Media apps** such as music and video streaming apps can keep tens of GiB of cache. Clear it through the app's own storage setting, which keeps downloads the user chose. Don't delete the folder.
- **Updater or installer staging:** abandoned staging directories from a failed plugin or app update can pile up thousands of copies. Uninstall through the owning tool first, then remove what is left only after confirming nothing references it.
- **`~/.cache` and similar folders** are not automatically disposable. Research data, benchmark results and model checkouts end up there too, so attribute contents before calling them cache.
- **Agent and IDE history** (conversation databases, session logs) is user data. Report it and keep it.

## Windows specifics

- **Hibernation file, pagefile and storage reserve** count as used space: several GiB each, visible with `powercfg /a`, `Get-CimInstance Win32_PageFileUsage` and `DISM /Online /Get-ReservedStorageState`. Changing them is a system decision, not a cleanup.
- **Don't use `compact /s` to measure.** It follows junctions and overcounted about fivefold.
- **WinSxS** is mostly hard links. See the Windows guide.
