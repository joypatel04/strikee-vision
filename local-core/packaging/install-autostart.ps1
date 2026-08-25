<#
  Strikee Vision - make the venue box start tracking on its own.

  After this, the PC powers on and tracking begins with nobody touching it.
  Staff open the dashboard only when they want to look.

  Run from the local-core directory, in PowerShell AS ADMINISTRATOR:

      powershell -ExecutionPolicy Bypass -File packaging\install-autostart.ps1

  Remove it again with:

      powershell -ExecutionPolicy Bypass -File packaging\install-autostart.ps1 -Uninstall

  Why it triggers at logon rather than at boot: this box reaches its cameras
  over a wifi adapter, and wifi is generally not connected before a user session
  exists. A task running as SYSTEM at boot would start, find no cameras, and sit
  there failing. Logon + auto-login gets a network that is actually up. Enable
  auto-login separately (netplwiz, or Sysinternals Autologon).
#>
[CmdletBinding()]
param(
    [string] $VenueId = "all",
    [int]    $DelaySeconds = 45,
    [switch] $Headless,
    [switch] $Uninstall,
    [switch] $NoPowerConfig
)

$ErrorActionPreference = "Stop"
$TaskName = "StrikeeVision"

function Ok   ($m) { Write-Host "  OK    $m" -ForegroundColor Green }
function Warn ($m) { Write-Host "  WARN  $m" -ForegroundColor Yellow }
function Bad  ($m) { Write-Host "  FAIL  $m" -ForegroundColor Red }
function Step ($m) { Write-Host "`n$m" -ForegroundColor Cyan }

# --- administrator? -----------------------------------------------------------
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Bad "Run this in PowerShell started with 'Run as administrator'."
    exit 1
}

# --- uninstall ----------------------------------------------------------------
if ($Uninstall) {
    Step "Removing autostart"
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Ok "scheduled task '$TaskName' removed"
    } else {
        Warn "no scheduled task named '$TaskName'"
    }
    Write-Host "`nSleep settings were left as they are. Restore them with:" -ForegroundColor White
    Write-Host "  powercfg /change standby-timeout-ac 30" -ForegroundColor DarkGray
    exit 0
}

# --- where are we? ------------------------------------------------------------
Step "Checking the installation"
$root = (Get-Location).Path
if (-not (Test-Path (Join-Path $root "pyproject.toml"))) {
    Bad "Run this from the local-core directory."
    exit 1
}
$exe = Join-Path $root ".venv\Scripts\strikee-core.exe"
if (-not (Test-Path $exe)) {
    Bad "$exe not found. Run packaging\windows-setup.bat first."
    exit 1
}
Ok "found $exe"

foreach ($model in @("best.pt")) {
    if (Test-Path (Join-Path $root $model)) { Ok "$model present" }
    else { Bad "$model missing - the pipeline cannot detect anything without it."; exit 1 }
}

# --- .env ---------------------------------------------------------------------
# The task starts from a bare environment, so settings MUST live in the file.
Step "Writing settings to .env"
$envPath = Join-Path $root ".env"
if (-not (Test-Path $envPath)) {
    $example = Join-Path $root ".env.example"
    if (Test-Path $example) { Copy-Item $example $envPath; Ok "created .env from .env.example" }
    else { New-Item -ItemType File -Path $envPath | Out-Null; Ok "created empty .env" }
}

function Set-EnvValue([string]$Key, [string]$Value) {
    $lines = @(Get-Content -LiteralPath $envPath -ErrorAction SilentlyContinue)
    $found = $false
    $out = foreach ($line in $lines) {
        if ($line -match "^\s*#?\s*$([regex]::Escape($Key))\s*=") { $found = $true; "$Key=$Value" }
        else { $line }
    }
    if (-not $found) { $out = $out + "$Key=$Value" }
    Set-Content -LiteralPath $envPath -Value $out -Encoding UTF8
    Ok "$Key=$Value"
}

Set-EnvValue "STRIKEE_AUTOSTART_VENUE" $VenueId
if ($Headless) { Set-EnvValue "STRIKEE_HEADLESS" "1" }

# --- the scheduled task -------------------------------------------------------
Step "Registering the scheduled task"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Warn "replaced the existing '$TaskName' task"
}

# WorkingDirectory matters more than it looks: .env, strikee.db, best.pt and the
# snapshots folder are all resolved relative to it.
$action = New-ScheduledTaskAction -Execute $exe -WorkingDirectory $root

$delay = [System.Xml.XmlConvert]::ToString([TimeSpan]::FromSeconds($DelaySeconds))
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = $delay      # let wifi associate before the first grab

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$taskPrincipal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
    -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $taskPrincipal `
    -Description "Strikee Vision local core - starts tracking on logon." | Out-Null
Ok "task '$TaskName' registered (at logon, +${DelaySeconds}s, restarts up to 5x)"

# --- keep the machine awake ---------------------------------------------------
if (-not $NoPowerConfig) {
    Step "Stopping the PC from sleeping"
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    powercfg /change monitor-timeout-ac 15
    Ok "sleep and hibernate disabled on AC (screen still turns off after 15 min)"
}

# --- done ---------------------------------------------------------------------
Write-Host "`n================ READY ================" -ForegroundColor Green
Write-Host @"

Test it now, without rebooting:

  Start-ScheduledTask -TaskName $TaskName
  Start-Sleep 20
  Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo

LastTaskResult 0 means it started cleanly. Then open the dashboard:

  http://127.0.0.1:8760/

Check two things there:
  * the System check panel - every setting you put in .env should read
    "env file", not "default"
  * the banner at the top - it names any camera or sync fault, and which
    adapter to look at

Still to do by hand, once:
  * enable Windows auto-login for this user (netplwiz), or the task waits
    forever at the lock screen after a power cut

"@ -ForegroundColor White
