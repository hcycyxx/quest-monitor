param([switch]$ReplacePanel)
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$entryPath = Join-Path $projectRoot 'sidequest_v10.py'
$pythonPath = Join-Path $env:LOCALAPPDATA 'SideQuestV10Runtime\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw '新版运行环境尚未安装，请按 RELEASE_Codex_UI_V10_20261106.md 操作。'
}
$oldPanelPath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'ui\quest_window.py'))
$legacyPanels = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -and
    $_.CommandLine.Replace('/','\').Contains($oldPanelPath)
})
if ($legacyPanels.Count -gt 0 -and -not $ReplacePanel) {
    throw '旧面板仍在运行。确认切换后，加 -ReplacePanel 启动；只关闭旧面板，保留后台和任务数据。'
}
if ($ReplacePanel) {
    foreach ($panelProcess in $legacyPanels) {
        Stop-Process -Id $panelProcess.ProcessId -ErrorAction Stop
    }
}
# Starting the UI does not restart, resume, pause, or duplicate the workers.
Start-Process -FilePath $pythonPath -ArgumentList @('"'+$entryPath+'"') -WorkingDirectory $projectRoot -WindowStyle Hidden
