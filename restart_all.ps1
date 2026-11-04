# Restart the panel and, unless paused, the background services.
# ASCII only: PowerShell 5.1 reads .ps1 as ANSI and mangles non-ASCII comments.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

# Only touch processes that belong to THIS checkout: match the script name and
# the project root, otherwise a second copy elsewhere on the machine gets killed.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*quest_window*" -and $_.CommandLine -like "*$root*" } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Output "killed panel $($_.ProcessId)"
    }
Start-Sleep -Seconds 2

$flag = $root + "\config\paused"
if (Test-Path -LiteralPath $flag) {
    Write-Output "state: PAUSED"
} else {
    python engine/ctl.py resume
}
python engine/ctl.py panel
Start-Sleep -Seconds 3
python engine/ctl.py
