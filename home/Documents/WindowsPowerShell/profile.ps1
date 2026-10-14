# Add ~/.local/bin to PATH
$localBin = Join-Path $HOME ".local\bin"
if (-not (($env:PATH -split ';') -icontains $localBin)) {
    $env:PATH = "$localBin;$env:PATH"
}

# mise (shims only — mise activate does not support Windows PowerShell 5.1)
$miseShims = Join-Path $HOME "AppData\Local\mise\shims"
if (-not (($env:PATH -split ';') -icontains $miseShims)) {
    $env:PATH = "$miseShims;$env:PATH"
}
