# SideQuest local version backup.
#
# Runs automatically after every commit via .git/hooks/post-commit, or manually:
#   powershell -ExecutionPolicy Bypass -File tools\backup.ps1
#
# Everything lands OUTSIDE the workspace, so wiping the workspace cannot take it:
#   %USERPROFILE%\sidequest-archive.git    bare repo with all branches and tags
#   %USERPROFILE%\sidequest-backups\       timestamped bundles + task-state snapshots
#
# Why this exists: on 2026-11-05 09:24 the whole workspace was wiped. The code
# came back from GitHub, but config\quest_state.json (the real task data) was
# gone for good. So besides git history we snapshot the state file separately.
#
# NOTE: keep this file pure ASCII. Windows PowerShell 5.1 reads .ps1 as ANSI and
# mangles non-ASCII bytes, which can break the script.

param(
    [int]$KeepBundles = 40,
    [int]$KeepStates = 200
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$archive = Join-Path $env:USERPROFILE "sidequest-archive.git"
$store = Join-Path $env:USERPROFILE "sidequest-backups"

if (-not (Test-Path $store)) {
    New-Item -ItemType Directory -Path $store -Force | Out-Null
}

# 1. Bare repo must exist and be wired up as a remote.
if (-not (Test-Path $archive)) {
    git init --bare $archive | Out-Null
}
$remotes = git -C $root remote
if ($remotes -notcontains "archive") {
    git -C $root remote add archive $archive
}

# 2. Push every branch and tag.
$rev = (git -C $root rev-parse --short HEAD).Trim()
git -C $root push --quiet archive --all --tags 2>$null
Write-Host "pushed $rev -> $archive"

# 3. One bundle file: offline-clonable, survives the bare repo disappearing.
$bundle = Join-Path $store "sidequest-$rev.bundle"
git -C $root bundle create $bundle --all 2>$null | Out-Null
Write-Host "bundle $bundle"

# 4. Snapshot the task state. It is gitignored but it is the most valuable file.
$state = Join-Path $root "config\quest_state.json"
if (Test-Path $state) {
    $snap = Join-Path $store ("state-{0}-{1}.json" -f (Get-Date -Format "yyyyMMdd-HHmmss"), $rev)
    Copy-Item $state $snap -Force
    Write-Host "state  $snap"
}

# 5. Prune old artifacts.
Get-ChildItem $store -Filter "sidequest-*.bundle" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip $KeepBundles |
    Remove-Item -Force -ErrorAction SilentlyContinue

Get-ChildItem $store -Filter "state-*.json" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip $KeepStates |
    Remove-Item -Force -ErrorAction SilentlyContinue

Write-Host ("done. store has {0} bundles, {1} state snapshots" -f `
    (Get-ChildItem $store -Filter "*.bundle").Count, `
    (Get-ChildItem $store -Filter "state-*.json").Count)
