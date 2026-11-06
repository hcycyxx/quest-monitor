param([switch]$ReplacePanel)
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$entryPath = Join-Path $projectRoot 'sidequest_v10_4.py'
$pythonPath = Join-Path $env:LOCALAPPDATA 'SideQuestV10Runtime\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'SideQuest V10 桌面运行环境未安装。' }
$panelPaths = @('ui\quest_window.py','ui\quest_window_v10.py','ui\quest_window_v10_1.py','sidequest_v10.py','sidequest_v10_1.py','sidequest_v10_2.py','sidequest_v10_3.py','sidequest_v10_4.py') | ForEach-Object {
    [System.IO.Path]::GetFullPath((Join-Path $projectRoot $_))
}
$panels = @(Get-CimInstance Win32_Process | Where-Object {
    if ($_.Name -notin @('python.exe','pythonw.exe') -or -not $_.CommandLine) { return $false }
    $commandText = $_.CommandLine.Replace('/','\')
    foreach ($candidatePath in $panelPaths) {
        if ($commandText.Contains($candidatePath)) { return $true }
    }
    return $false
})
if ($panels.Count -gt 0 -and -not $ReplacePanel) { throw '已有面板运行。确认替换后使用 -ReplacePanel。' }
if ($ReplacePanel) {
    foreach ($panelProcess in $panels) {
        Stop-Process -Id $panelProcess.ProcessId -ErrorAction SilentlyContinue
    }
}
# Only the UI is replaced. The watcher, model engine, pause flag and tasks are untouched.
Start-Process -FilePath $pythonPath -ArgumentList @('"'+$entryPath+'"') -WorkingDirectory $projectRoot -WindowStyle Hidden
