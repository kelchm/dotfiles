# Starship prompt
Invoke-Expression (&starship init powershell)

# mise
mise activate pwsh | Invoke-Expression

# 1Password SSH agent (Windows named pipe)
$env:SSH_AUTH_SOCK = "\\.\pipe\openssh-ssh-agent"
