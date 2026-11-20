# Windows

## Identify the volume

Start in native PowerShell, including when the lead is a WSL disk image. Find the volume that contains the path. Include volumes mounted in folders and look up drive mappings before treating the same storage as two volumes.

```powershell
Get-Volume | Select-Object DriveLetter, Path, FileSystem, Size, SizeRemaining
Get-Partition | Select-Object DiskNumber, PartitionNumber, AccessPaths
```

Record bytes and label GiB (bytes divided by `1GB` in PowerShell) or decimal GB. `SizeRemaining` is a volume reading. A caller quota, a thin pool and Windows Storage Reserve can affect availability. Use `GetDiskSpaceInformationW` if you need the separate actual, caller, used and reserved counters. The volume storage reserve is part of total reserve. Treat VSS usage as unknown when `vssadmin list shadowstorage` or `vssadmin list shadows` needs permissions you lack. [Windows disk-space counters](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/ns-fileapi-disk_space_information)

## Rank and attribute

Use Storage settings for a broad breakdown and follow its large items to actual directories, apps or services. Select bounded roots such as user profiles, project workspaces, application data, package stores and temporary directories. Preserve read errors. Check junctions, reparse points and offline/cloud entries before descent to avoid duplicate trees, other volumes and hydration.

For a quick discovery pass without extra tools, rank the immediate children of an ordinary local folder by logical length. Choose a small enough root first and verify that its ancestors are in the intended volume and outside reparse or cloud paths. The skip mask covers reparse, offline and recall flags. Skipped entries and errors mean partial coverage.

```powershell
$root = 'C:\path\to\inspect'
$skip = 0x441400
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

A `Length` sum counts names and represents logical bytes. Compression, sparse files, hard links, alternate streams and shared clusters can change the storage figure. For selected ordinary trees, use an available allocation report and check its scope. Sysinternals `du.exe -c -l 1 <path>` (if already installed) reports logical and on-disk columns. `-u` counts every hard link. Built-in `diskusage.exe` can help where installed and permitted. Use its local help and retain access errors. [Sysinternals Disk Usage](https://learn.microsoft.com/en-us/sysinternals/downloads/du)

## Verify a cleanup lead

- **Specific files:** check hard-link names with `fsutil hardlink list <path>` where permitted and look for alternate streams with `Get-Item -LiteralPath $file -Stream *`. A handle-based tool can measure stream allocation and deduplicate hard links by volume and file ID. Compare distinct names being removed with link count. ReFS clones can share clusters between different file IDs. Per-file allocation and a directory inventory do not establish joint reclaim. [File identity](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info) · [Volume extent mapping](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-fsctl_get_retrieval_pointers)
- **Windows and application storage:** use the owning tool. For example, Storage settings identifies system-managed cleanup, and `Dism.exe /Online /Cleanup-Image /AnalyzeComponentStore` reports WinSxS sharing when elevated analysis is authorized. Treat user data, backups, installer state and project files separately. [Component store accounting](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/determine-the-actual-size-of-the-winsxs-folder)
- **WSL and VMs:** identify WSL distributions with `wsl --list --verbose` where available. Measure the backing image on the host and guest filesystem usage separately. Starting a stopped guest changes state. Use the guest/container owner to inspect or clean it. Verify host allocation after any supported trim or compaction. [WSL disk space](https://learn.microsoft.com/en-us/windows/wsl/vhd-size)

If allocation or retained references remain unknown, say which and keep the estimate unknown. After authorized cleanup, repeat the same volume measurement. Consider VSS, the Recycle Bin, open handles and backing images when little space returns.
