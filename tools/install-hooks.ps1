# Put the post-commit backup hook into .git/hooks/.
#
# .git/hooks/ is not version controlled, so a fresh clone has no hook. Run this
# once after cloning, or let install.ps1 call it.
#
#   powershell -ExecutionPolicy Bypass -File tools\install-hooks.ps1
#
# Keep this file pure ASCII: Windows PowerShell 5.1 reads .ps1 as ANSI.

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$src = Join-Path $root "tools\post-commit"
$dst = Join-Path $root ".git\hooks\post-commit"

if (-not (Test-Path (Join-Path $root ".git"))) {
    Write-Host "not a git checkout, nothing to install"
    exit 0
}

if (-not (Test-Path $src)) {
    Write-Host "missing tools\post-commit"
    exit 1
}

New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null
Copy-Item $src $dst -Force
Write-Host "installed hook -> $dst"
