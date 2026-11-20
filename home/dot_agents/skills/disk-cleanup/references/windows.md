# Windows

Work in native PowerShell, including when the lead is a WSL or VM disk image.

## 1. Find the volume

```powershell
Get-Volume | Select-Object DriveLetter, Path, FileSystem, Size, SizeRemaining
Get-Partition | Select-Object DiskNumber, PartitionNumber, AccessPaths
```

- A volume can be mounted in a folder as well as at a drive letter, and `subst` or mapped drives can point at the same storage. Match on `Path` before treating two letters as two volumes.
- Report bytes and say whether you converted to GiB (PowerShell's `1GB`) or decimal GB.
- Per-user quotas, the Windows storage reserve and thin provisioning can make usable space differ from `SizeRemaining`. `GetDiskSpaceInformationW` reports the caller, used and reserved counters separately. [Disk-space counters](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/ns-fileapi-disk_space_information)
- Shadow copies (`vssadmin list shadowstorage`) need elevation. Without it, treat VSS usage as unknown.

## 2. Rank directories

Start with Settings > System > Storage for a broad breakdown, then follow its large categories to real folders: user profiles, `AppData`, project workspaces, package caches and `C:\ProgramData`.

Watch for junctions, symbolic links and OneDrive placeholders. Following them double-counts trees, crosses volumes or downloads cloud files. The script below ranks the children of a local folder by logical size and does not follow any of them below `$root`. It cannot tell whether `$root` itself is reached through a junction, so first check that none of its ancestors has the `ReparsePoint` attribute and that `Get-Volume -FilePath $root` is the volume you mean. Skipped entries and errors mean partial coverage.

```powershell
$root = 'C:\path\to\inspect'
$skip = 0x441400  # ReparsePoint, Offline, RecallOnOpen, RecallOnDataAccess
$base = Get-Item -LiteralPath $root -Force -ErrorAction Stop
if (-not $base.PSIsContainer -or ([int]$base.Attributes -band $skip)) {
    throw 'Choose an ordinary local directory'
}
Get-ChildItem -LiteralPath $root -Force -ErrorAction Continue | ForEach-Object {
    $lead = $_.FullName
    $pending = [System.Collections.Generic.Stack[System.IO.FileSystemInfo]]::new()
    $pending.Push($_)
    $bytes = 0L
    $skipped = 0
    $readErrors = @()
    while ($pending.Count) {
        $item = $pending.Pop()
        if ([int]$item.Attributes -band $skip) { $skipped++; continue }
        if ($item.PSIsContainer) {
            Get-ChildItem -LiteralPath $item.FullName -Force -ErrorAction Continue -ErrorVariable +readErrors |
                ForEach-Object { $pending.Push($_) }
        } else { $bytes += $item.Length }
    }
    [pscustomobject]@{Path=$lead; LogicalBytes=$bytes; Skipped=$skipped; Errors=$readErrors.Count}
} | Sort-Object LogicalBytes -Descending
```

It works in Windows PowerShell 5.1 and PowerShell 7. `Length` is logical size, so NTFS compression, sparse files and hard links make it differ from allocation. For allocation, Sysinternals `du.exe -c -l 1 <path>` (if installed) reports logical and on-disk columns. Its `-u` flag counts each hard link separately. Recent Windows builds also include `diskusage.exe`; read its built-in help first. [Sysinternals Disk Usage](https://learn.microsoft.com/en-us/sysinternals/downloads/du)

## 3. Check what keeps data after deletion

- **Hard links:** `fsutil hardlink list <file>` (where permitted). Data stays while any other name remains.
- **Alternate data streams:** `Get-Item -LiteralPath $file -Stream *`. They are excluded from `Length`.
- **ReFS block clones and Dev Drive:** clones share clusters between files, so per-file allocation overstates what deleting one copy frees.
- **Shadow copies and the Recycle Bin** keep deleted data until they are cleared.
- **Open handles** keep a file in use. Sysinternals `handle.exe <path>` finds the process.

## Common large owners

- **Windows itself:** Storage settings > Temporary files lists what Windows can clean safely. Much of WinSxS's apparent size is hard links to files elsewhere in Windows. `Dism.exe /Online /Cleanup-Image /AnalyzeComponentStore` (elevated) reports the store's actual size, the number of reclaimable packages and whether cleanup is recommended. It does not say how many bytes cleanup will free, so leave that unknown. [WinSxS size](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/determine-the-actual-size-of-the-winsxs-folder)
- **WSL and VMs:** `wsl --list --verbose` lists distributions. Each one's `ext4.vhdx` grows as the guest writes, and unless it is set to sparse mode it does not shrink when guest files are deleted. Measure guest usage and the host image separately, check the sparse setting before recommending compaction, and remeasure the image afterward. [WSL disk space](https://learn.microsoft.com/en-us/windows/wsl/vhd-size)
- **Docker Desktop, Hyper-V and other VM images:** use the owning tool to inspect and clean them. Starting a stopped VM changes its state.
- **Package and build caches:** npm, pnpm, NuGet (`%USERPROFILE%\.nuget\packages`), Cargo, Gradle, Visual Studio and project build output. Use the owning tool's cleanup command.

## After cleanup

Repeat the same `Get-Volume` measurement. If less space returned than expected, check shadow copies, the Recycle Bin, open handles and VM images that still need compaction.
