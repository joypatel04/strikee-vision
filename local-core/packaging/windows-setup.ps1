<#
  Strikee Vision — Windows venue-box bring-up.

  Run this from the local-core directory on the club PC. It does the whole
  one-time install and then proves the stack actually works, in the order that
  fails fastest:

    1. Python present and a sane version
    2. Model weights present   (they are gitignored — a clone does NOT have them)
    3. venv + dependencies
    4. strikee-doctor: loads best.pt, runs one REAL inference, decodes one DVR
       frame. This is the check that catches an old CPU whose torch wheel won't
       run, which is the single most likely reason tomorrow goes wrong.

  Usage (from local-core\):
      powershell -ExecutionPolicy Bypass -File packaging\windows-setup.ps1 `
          -Rtsp "rtsp://USER:PASS@192.168.0.108:554/cam/realmonitor?channel=1&subtype=0"

  Or just double-click packaging\windows-setup.bat, which wraps this.
#>
[CmdletBinding()]
param(
    [string] $Rtsp  = "",
    [string] $Model = "best.pt",
    [switch] $Turso,
    [switch] $SkipDoctor
)

$ErrorActionPreference = "Stop"

$script:Failed = $false
function Step($n, $msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Ok  ($msg)     { Write-Host "  OK    $msg" -ForegroundColor Green }
function Warn($msg)     { Write-Host "  WARN  $msg" -ForegroundColor Yellow }
function Bad ($msg)     { Write-Host "  FAIL  $msg" -ForegroundColor Red; $script:Failed = $true }

Write-Host "Strikee Vision - Windows bring-up" -ForegroundColor White

# --- 0. right directory? ----------------------------------------------------
Step 0 "Checking working directory"
if (-not (Test-Path "pyproject.toml")) {
    Bad "Run this from the local-core directory (no pyproject.toml here)."
    Write-Host "`n  cd C:\path\to\Strikee Vision\local-core" -ForegroundColor Yellow
    exit 1
}
Ok "in $(Get-Location)"

# --- 1. Python --------------------------------------------------------------
Step 1 "Locating Python 3.11/3.12"
# Each candidate is exe + its args, kept as separate elements so we never pass
# a $null argument to a native command.
$candidates = @(
    @("py",     @("-3.12")),
    @("py",     @("-3.11")),
    @("py",     @("-3")),
    @("python", @()),
    @("python3", @())
)
$pyExe = $null; $pyArgs = @(); $pyVer = ""
foreach ($cand in $candidates) {
    $exe = $cand[0]; $cargs = $cand[1]
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    try { $v = (& $exe @cargs --version 2>&1 | Out-String) } catch { continue }
    if ($v -match "Python (\d+)\.(\d+)") {
        $maj = [int]$Matches[1]; $min = [int]$Matches[2]
        if ($maj -eq 3 -and $min -ge 11) {
            $pyExe = $exe; $pyArgs = $cargs; $pyVer = "$maj.$min"; break
        }
    }
}
$py = (@($pyExe) + $pyArgs) -join " "
if (-not $pyExe) {
    Bad "No Python 3.11+ found. Install 3.12 from python.org (tick 'Add to PATH')."
    exit 1
}
Ok "$py  ->  Python $pyVer"
if ($pyVer -eq "3.13") { Warn "3.13 works but 3.12 has the best-tested torch/ultralytics wheels." }

# --- 2. model weights (gitignored - the classic gotcha) ---------------------
Step 2 "Checking model weights"
foreach ($m in @($Model, "yolo11n.pt")) {
    if (Test-Path $m) {
        Ok "$m  ($([math]::Round((Get-Item $m).Length / 1MB, 1)) MB)"
    } else {
        Bad "$m is MISSING."
        Write-Host "        *.pt is gitignored, so a git clone never brings the models." -ForegroundColor Yellow
        Write-Host "        Copy it from the Mac (local-core\) onto this box via USB." -ForegroundColor Yellow
    }
}
if ($script:Failed) { exit 1 }

# --- 3. venv + dependencies -------------------------------------------------
Step 3 "Creating virtualenv and installing dependencies"
if (-not (Test-Path ".venv")) {
    & $pyExe @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { Bad "could not create the virtualenv"; exit 1 }
    Ok "created .venv"
} else {
    Ok ".venv already exists (reusing)"
}

$vpy = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { Bad "venv looks broken - delete .venv and re-run."; exit 1 }

$extras = "perception,desktop"
if ($Turso) { $extras = "$extras,turso" }
Write-Host "  installing .[$extras] - this pulls torch, expect several minutes..." -ForegroundColor DarkGray
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -e ".[$extras]"
if ($LASTEXITCODE -ne 0) { Bad "pip install failed - see the error above."; exit 1 }
Ok "dependencies installed"

# --- 4. the real proof ------------------------------------------------------
if ($SkipDoctor) {
    Warn "skipping strikee-doctor (-SkipDoctor)"
} else {
    Step 4 "Running strikee-doctor (loads the model, runs one real inference)"
    $doctor = ".\.venv\Scripts\strikee-doctor.exe"
    if ($Rtsp) { & $doctor --model $Model --rtsp $Rtsp } else {
        Warn "no -Rtsp given: checking the model only, not the DVR stream"
        & $doctor --model $Model
    }
    if ($LASTEXITCODE -ne 0) {
        Bad "strikee-doctor reported a problem - send that output to Claude verbatim."
        exit 1
    }
    Ok "stack verified"
}

# --- next steps -------------------------------------------------------------
Write-Host "`n================ READY ================" -ForegroundColor Green
Write-Host @"

Next, in this same directory:

  1) Draw the table zones (one polygon per table; TWO on channel 6):
       .\.venv\Scripts\python.exe field_setup.py ``
           --source "rtsp://USER:PASS@192.168.0.108:554/cam/realmonitor?channel=1&subtype=0" ``
           --venue "Strikee Club"
     Repeat for channel 4, then channel 6 (draw table 3 AND table 4).

  2) Run it, with the debug log on so a miscount can be explained:
       set STRIKEE_DEBUG=1
       .\.venv\Scripts\strikee-core.exe

  3) Dashboard: http://127.0.0.1:8760/

Write down the real games on ONE table by hand while it runs - without that
ground truth you cannot judge the games log.

"@ -ForegroundColor White
