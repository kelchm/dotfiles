# Add ~/.local/bin to PATH
$localBin = Join-Path $HOME ".local\bin"
if (-not (($env:PATH -split ';') -contains $localBin)) {
    $env:PATH = "$localBin;$env:PATH"
}

# Starship prompt
if (Get-Command starship -ErrorAction SilentlyContinue) {
    Invoke-Expression (&starship init powershell)
}

# mise
if (Get-Command mise -ErrorAction SilentlyContinue) {
    mise activate pwsh | Out-String | Invoke-Expression
}
