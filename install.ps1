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

# --- 2b. optional content-capture deps ------------------------------------
# comtypes reads the UIA tree, winsdk calls the built-in Windows OCR, and
# rapidocr is a much more accurate OCR (3-5s per frame instead of 0.4s, but it
# does not misread table cells). All are local only. Missing packages are NOT
# fatal: the engine falls back to reading window titles only.
$haveDeps = & $py -c "import comtypes, winsdk; print('1')" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] content capture deps present (comtypes, winsdk)"
} else {
    Write-Host "[..] installing content capture deps (comtypes, winsdk)"
    & $py -m pip install --quiet --disable-pip-version-check comtypes winsdk 2>&1 | Out-Null
    & $py -c "import comtypes, winsdk" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] content capture enabled"
    } else {
        Write-Host "[!] could not install comtypes / winsdk." -ForegroundColor Yellow
        Write-Host "    The panel still works, but it will only see window titles."
        Write-Host "    Retry later with: pip install comtypes winsdk"
    }
}

# --- 2c. optional accurate OCR --------------------------------------------
# RapidOCR gets table cells right where the built-in OCR does not. It is a
# ~100MB download, so a failure here is only a warning: ocr_engine=auto falls
# back to the built-in OCR.
$haveRapid = & $py -c "import rapidocr, onnxruntime; print('1')" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] rapidocr present (accurate OCR)"
} else {
    Write-Host "[..] installing rapidocr (accurate OCR, ~100MB)"
    & $py -m pip install --quiet --disable-pip-version-check rapidocr onnxruntime 2>&1 | Out-Null
    & $py -c "import rapidocr, onnxruntime" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] accurate OCR enabled"
    } else {
        Write-Host "[!] could not install rapidocr." -ForegroundColor Yellow
        Write-Host "    Table cells may be misread. Retry: pip install rapidocr onnxruntime"
    }
}

# --- 2d. optional tray icon -----------------------------------------------
# pystray gives the tray icon that opens the daily summary. Without it the
# panel still runs; you just lose the tray menu.
$haveTray = & $py -c "import pystray; print('1')" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] pystray present (tray icon)"
} else {
    Write-Host "[..] installing pystray (tray icon)"
    & $py -m pip install --quiet --disable-pip-version-check pystray 2>&1 | Out-Null
    & $py -c "import pystray" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] tray icon enabled"
    } else {
        Write-Host "[!] could not install pystray." -ForegroundColor Yellow
        Write-Host "    The panel still works; the daily summary is only reachable from disk."
        Write-Host "    Retry later with: pip install pystray"
    }
}

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
$capOn = "on"
if ($eff.content_capture -eq $false) { $capOn = "off" }
Write-Host "  capture  : $capOn (content_level: $($eff.content_level))"
$docOn = "on"
if ($eff.doc_read -eq $false) { $docOn = "off" }
Write-Host "  doc_read : $docOn (ocr_engine: $($eff.ocr_engine))"
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
Write-Host "  - top bar buttons: skin / pause / always-on-top / pin / collapse / close"
Write-Host "  - pause really kills the samplers, so it stops costing tokens"
Write-Host "  - tray icon (bottom right): daily summary, history, settings, quit"
Write-Host ""
Write-Host "Logs: engine\engine_run.log"
Write-Host "Daily summary: summaries\YYYY-MM-DD.html (auto at 18:00)"
Write-Host "Stop: python engine\ctl.py pause"
