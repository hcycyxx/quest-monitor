# SideQuest installer. ASCII only: PowerShell 5.1 reads .ps1 as ANSI.
param(
    [string]$BaseUrl = "",
    [string]$ApiKey = "",
    [string]$Model = "",
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host ""
Write-Host "SideQuest installer" -ForegroundColor Cyan
Write-Host "root: $root"
Write-Host ""

# --- 1. python -------------------------------------------------------------
$py = $null
foreach ($cand in @("python", "python3", "py")) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source; break }
}
if (-not $py) {
    Write-Host "[X] Python not found in PATH." -ForegroundColor Red
    Write-Host "    Install Python 3.10+ from https://www.python.org/downloads/windows/"
    Write-Host "    Tick 'Add python.exe to PATH' and 'tcl/tk and IDLE' during setup."
    exit 1
}
$ver = & $py -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Host "[OK] python $ver at $py"

# --- 2. tkinter ------------------------------------------------------------
& $py -c "import tkinter" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[X] tkinter missing. Re-run the Python installer and enable 'tcl/tk and IDLE'." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] tkinter available"

# --- 3. config -------------------------------------------------------------
$cfgDir = Join-Path $root "config"
if (-not (Test-Path $cfgDir)) { New-Item -ItemType Directory -Path $cfgDir | Out-Null }

$cfg = Join-Path $cfgDir "llm.json"
$example = Join-Path $cfgDir "llm.example.json"

if ((Test-Path $cfg) -and ($BaseUrl -eq "") -and ($ApiKey -eq "") -and ($Model -eq "")) {
    Write-Host "[SKIP] config\llm.json already exists, left untouched"
} else {
    $obj = Get-Content $example -Raw | ConvertFrom-Json
    if ($BaseUrl -ne "") { $obj.base_url = $BaseUrl }
    if ($ApiKey  -ne "") { $obj.api_key  = $ApiKey }
    if ($Model   -ne "") { $obj.model    = $Model }
    $obj | ConvertTo-Json -Depth 4 | Set-Content -Path $cfg -Encoding UTF8
    Write-Host "[OK] wrote config\llm.json"
}

# state seed: the panel shows a few sample tasks until the model rewrites it
$state = Join-Path $cfgDir "quest_state.json"
if (-not (Test-Path $state)) {
    Copy-Item (Join-Path $cfgDir "quest_state.example.json") $state
    Write-Host "[OK] seeded config\quest_state.json from example"
}

# --- 4. show effective config ---------------------------------------------
$eff = Get-Content $cfg -Raw | ConvertFrom-Json
Write-Host ""
Write-Host "  base_url : $($eff.base_url)"
Write-Host "  model    : $($eff.model)"
$keyShown = $eff.api_key
if ($keyShown -and $keyShown.Length -gt 8) { $keyShown = $keyShown.Substring(0, 4) + "..." }
Write-Host "  api_key  : $keyShown"
Write-Host "  interval : $($eff.interval_seconds)s"
Write-Host ""

if ($eff.api_key -eq "YOUR_API_KEY") {
    Write-Host "[!] api_key is still the placeholder." -ForegroundColor Yellow
    Write-Host "    Edit config\llm.json, or re-run:"
    Write-Host "    .\install.ps1 -BaseUrl http://127.0.0.1:8899/v1 -ApiKey sk-xxx -Model deepseek-v4.1-flash"
    Write-Host ""
    if (-not $NoStart) {
        Write-Host "    Starting only the panel so the window is visible; analysis stays off."
        Write-Host ""
    }
}

# --- 5. reachability probe (non fatal) ------------------------------------
try {
    $probe = $eff.base_url.TrimEnd("/") + "/models"
    $r = Invoke-WebRequest -Uri $probe -UseBasicParsing -TimeoutSec 4 `
        -Headers @{ Authorization = "Bearer $($eff.api_key)" }
    if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) {
        Write-Host "[OK] endpoint reachable: $probe"
    } else {
        Write-Host "[!] endpoint answered $($r.StatusCode) - check base_url" -ForegroundColor Yellow
    }
} catch {
    Write-Host "[!] could not reach $probe" -ForegroundColor Yellow
    Write-Host "    Local gateways (Ollama / LM Studio / vLLM) must be running first."
}

# --- 6. start --------------------------------------------------------------
Write-Host ""
if ($NoStart) {
    Write-Host "Done. Start later with:"
    Write-Host "  python engine\ctl.py panel"
    Write-Host "  python engine\ctl.py resume"
    exit 0
}

if ($eff.api_key -eq "YOUR_API_KEY") {
    & $py "engine\ctl.py" panel
} else {
    & $py "engine\ctl.py" panel
    Start-Sleep -Seconds 1
    & $py "engine\ctl.py" resume
}

# Version backup hook: every commit gets mirrored to a bare repo + bundle under
# %USERPROFILE%, outside the workspace. Skipped silently when not a git checkout.
$hookScript = Join-Path $PSScriptRoot "tools\install-hooks.ps1"
if (Test-Path $hookScript) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $hookScript | Out-Null
}

Write-Host ""
Write-Host "Status:" -ForegroundColor Cyan
& $py "engine\ctl.py"
Write-Host ""
Write-Host "Panel should now sit at the top-right corner." -ForegroundColor Cyan
Write-Host "  - click the title bar to drag it"
Write-Host "  - top bar buttons: skin / pause / pin / collapse / close"
Write-Host "  - pause really kills the samplers, so it stops costing tokens"
Write-Host ""
Write-Host "Logs: engine\engine_run.log"
Write-Host "Stop: python engine\ctl.py pause"
