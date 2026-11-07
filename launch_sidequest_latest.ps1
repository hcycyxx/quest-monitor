param([switch]$ReplacePanel)
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$pythonPath = Join-Path $env:LOCALAPPDATA 'SideQuestV10Runtime\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'SideQuest 桌面运行环境未安装。' }
$entryPath = Join-Path $projectRoot 'sidequest_latest.py'
$launchMode = if ($ReplacePanel) { '--replace-panel' } else { '--open' }
Start-Process -FilePath $pythonPath -ArgumentList @('"'+$entryPath+'"', $launchMode) -WorkingDirectory $projectRoot -WindowStyle Hidden
