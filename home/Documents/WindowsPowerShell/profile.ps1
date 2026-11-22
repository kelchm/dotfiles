# mise (shims + command wrappers — mise activate does not support Windows PowerShell 5.1)
# Prepend low-to-high so precedence is: ~/.local/bin > command-wrappers\bin > shims.
$miseShims = Join-Path $HOME "AppData\Local\mise\shims"
$miseWrappers = Join-Path $HOME "AppData\Local\mise\command-wrappers\bin"
$localBin = Join-Path $HOME ".local\bin"
foreach ($dir in @($miseShims, $miseWrappers, $localBin)) {
    if (Test-Path $dir) {
        $rest = ($env:PATH -split ';') | Where-Object { $_ -ne '' -and $_ -ine $dir }
        $env:PATH = (@($dir) + $rest) -join ';'
    }
}
