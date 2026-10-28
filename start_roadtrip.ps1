<#
.SYNOPSIS
  One-command Roadtrip stack: V2 monitor, p2 controller, one attempt.
.DESCRIPTION
  Self-contained V2 launcher. Uses the already-running Uncrashed session (never launches the game).
  Verifies readiness, refuses duplicate controllers, runs one train attempt
  with V2 map overrides, waits for the monitor report, then shuts down cleanly.
  Flight code and history are never modified; every log is append-only.
  Runner and monitor output is captured to logs/launcher_<timestamp>/ together
  with an incident file if anything aborts, so a startup failure stays
  diagnosable after its windows close.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\start_roadtrip.ps1 -Label "my flight"
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\start_roadtrip.ps1 -DryRun
#>
[CmdletBinding()]
param(
  [string]$Label = "roadtrip launcher flight",
  [string]$Version = "p2_fast_baseline",
  [string]$Course = "roadtrip_full",
  [string]$Split = "train",
  [int]$Timeout = 1200,
  [int]$BeatTimeoutSec = 150,
  [switch]$SkipTiltCheck,
  [switch]$KeepAlive,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LocalVenv = Join-Path $Root ".venv\Scripts\python.exe"
$Py = if (Test-Path $LocalVenv) { $LocalVenv } else { Join-Path $Root "..\.venv\Scripts\python.exe" }
$VRoot = Join-Path $Root "versions\$Version"
$MonLog = Join-Path $Root "eval\roadtrip"
$DiagDir = Join-Path $Root ("logs\launcher_" + (Get-Date -Format "yyyyMMdd_HHmmss"))

function Fail([string]$msg) { throw "ABORT: $msg" }
function Info([string]$msg) { Write-Host $msg }

function EpochNow { return [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }

function Find-Runners {
  $found = @()
  $beats = @()
  $vdir = Join-Path $Root "versions"
  if (Test-Path $vdir) {
    $beats += Get-ChildItem $vdir -Directory -ErrorAction SilentlyContinue |
      ForEach-Object { Join-Path $_.FullName "results\_runner.json" }
  }
  foreach ($b in $beats) {
    if (Test-Path $b) {
      try {
        $j = Get-Content $b -Raw | ConvertFrom-Json
        $now = EpochNow
        # NOTE: $now must be captured first. (EpochNow - $j.time) parses the
        # function name as a command and silently drops the subtraction,
        # returning raw epoch and breaking every age check.
        if (($now - $j.time) -lt 15) {
          $found += "heartbeat $b (age $([math]::Round(($now - $j.time), 1))s)"
        }
      } catch {}
    }
  }
  try {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction Stop |
      Where-Object { $_.CommandLine -like "*pilot/runner.py*" -or $_.CommandLine -like "*pilot\runner.py*" } |
      ForEach-Object { $found += "process pid $($_.ProcessId): $($_.CommandLine)" }
  } catch {}
  return $found
}

function Test-Game {
  $raw = & $Py (Join-Path $Root "tools\game.py") status
  if ($LASTEXITCODE -ne 0) { return @{ ok = $false; why = "game.py status failed" } }
  $st = $raw | ConvertFrom-Json
  if ($st.running -eq $false -or -not $st.hwnd) {
    return @{ ok = $false; why = "Uncrashed window not found (open the game with Roadtrip loaded first)" }
  }
  if ($st.minimized) { return @{ ok = $false; why = "game is minimized" } }
  $c = $st.client
  if ($c[2] -ne 1920 -or $c[3] -ne 1080) {
    Info "WARNING: client is $($c[2])x$($c[3]); pilot boxes assume 1920x1080."
  }
  return @{ ok = $true; why = "hwnd $($st.hwnd) pid $($st.pid)" }
}

function Get-V2Overrides {
  $rootPy = $Root -replace '\\', '/'
  $code = "import sys; sys.path.insert(0, '$rootPy'); from droneai import maps; " +
    "print(' '.join('--set ' + o for o in maps.to_overrides('roadtrip', '$Course')))"
  $out = & $Py -c $code
  if ($LASTEXITCODE -ne 0 -or -not $out) { Fail "V2 map overrides failed" }
  return @($out.Trim() -split '\s+')
}

function Get-HeartbeatAge {
  param([string]$BeatPath)
  if (-not (Test-Path $BeatPath)) { return @{ age = $null; content = $null } }
  try {
    $j = Get-Content $BeatPath -Raw | ConvertFrom-Json
    $t = $j.time -as [double]
    if ($t -eq $null) { return @{ age = $null; content = $j } }
    $now = EpochNow
    return @{ age = ($now - $t); content = $j }
  } catch {
    return @{ age = $null; content = $null }
  }
}

$monProc = $null
$runProc = $null
$startedMonitor = $false
$startedRunner = $false
$incident = @{ started = (Get-Date -Format o); label = $Label; version = $Version }

function Stop-Stack {
  if ($startedRunner -and $runProc) {
    $runProc.Refresh()
    if (-not $runProc.HasExited) {
      Info "Quitting runner (pid $($runProc.Id))..."
      & $Py (Join-Path $VRoot "tools\job.py") quit --no-pause | Out-Null
      $beat = Join-Path $VRoot "results\_runner.json"
      for ($i = 0; $i -lt 60 -and (Test-Path $beat); $i++) { Start-Sleep -Milliseconds 500 }
      # The venv python is a shim around the real interpreter and can lag it
      # by a few seconds on exit; give the process its own grace before force.
      for ($i = 0; $i -lt 20; $i++) {
        $runProc.Refresh()
        if ($runProc.HasExited) { break }
        Start-Sleep -Milliseconds 500
      }
      $runProc.Refresh()
      if (-not $runProc.HasExited) {
        Stop-Process -Id $runProc.Id -Force
        Info "Runner force-stopped (quit job did not exit it)."
      } else {
        Info "Runner exited cleanly."
      }
    }
  }
  if ($startedMonitor -and $monProc) {
    $monProc.Refresh()
    if (-not $monProc.HasExited) {
      Stop-Process -Id $monProc.Id -Force
      Info "Monitor stopped."
    }
  }
}

function Write-Incident {
  param([string]$Status)
  $incident["status"] = $Status
  $incident["ended"] = (Get-Date -Format o)
  $incident | ConvertTo-Json -Depth 4 | Out-File (Join-Path $DiagDir "incident.json") -Encoding utf8
}

# ---- readiness -----------------------------------------------------------
try {
  if (-not (Test-Path $Py)) { Fail "no interpreter at $Py" }
  if (-not (Test-Path $VRoot)) { Fail "no version dir $VRoot" }
  if ($Course -notin @("roadtrip_full", "roadtrip_g10")) {
    Fail "V2 maps only roadtrip_full/roadtrip_g10 (got $Course)"
  }

  $failures = @()
  $game = Test-Game
  Info "game: $($game.why)"
  if (-not $game.ok) { $failures += $game.why }
  $dups = @(Find-Runners)
  if ($dups.Count -gt 0) {
    Info ("controllers busy:`n  " + ($dups -join "`n  "))
    $failures += "controller already running"
  } else {
    Info "controllers: none running"
  }
  $queued = @(Get-ChildItem (Join-Path $VRoot "jobs") -File -Filter "*.json" -ErrorAction SilentlyContinue)
  if ($queued.Count -gt 0) {
    Info "job queue: $($queued.Count) queued"
    $failures += "$($queued.Count) queued job(s)"
  } else {
    Info "job queue: empty"
  }
  $setArgs = Get-V2Overrides
  Info "V2 overrides: $($setArgs -join ' ')"

  if ($DryRun) {
    Info "DRY RUN: would start monitor, then runner, then one attempt (label '$Label')."
    Info "DRY RUN: would wait for the monitor report, then shut down (KeepAlive: $KeepAlive)."
    if ($failures.Count -gt 0) { Fail ("readiness: " + ($failures -join "; ")) }
    Info "DRY RUN: all checks pass."
    exit 0
  }
  if ($failures.Count -gt 0) { Fail ($failures -join "; ") }
  if (-not $SkipTiltCheck) {
    Info "Probing camera tilt (Down, shot, Up restores)..."
    & $Py (Join-Path $Root "tools\game.py") key DOWN | Out-Null
    Start-Sleep -Seconds 1
    $shotOut = & $Py (Join-Path $Root "tools\game.py") shot --scale 0.5
    & $Py (Join-Path $Root "tools\game.py") key UP | Out-Null
    Info "Tilt probe shot: $shotOut"
    $ans = Read-Host "Game should have flashed Tilt twice (expect 30 at rest). Proceed? (y/n)"
    if ($ans -ne "y") { Fail "tilt not confirmed" }
  }

  # ---- start (monitor first, then controller) ------------------------------
  New-Item -ItemType Directory -Force -Path $DiagDir | Out-Null
  New-Item -ItemType Directory -Force -Path $MonLog | Out-Null
  $monOut = Join-Path $DiagDir "monitor.out.log"
  $monErr = Join-Path $DiagDir "monitor.err.log"
  $runOut = Join-Path $DiagDir "runner.out.log"
  $runErr = Join-Path $DiagDir "runner.err.log"
  Info "Child output goes to $DiagDir"
  Info "Starting V2 monitor..."
  $monProc = Start-Process -FilePath $Py `
    -ArgumentList "-m", "droneai.monitor", "--version", $Version `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $monOut -RedirectStandardError $monErr `
    -WindowStyle Hidden -PassThru
  $startedMonitor = $true
  Start-Sleep -Seconds 3
  $monProc.Refresh()
  if ($monProc.HasExited) { Fail "monitor exited immediately (code $($monProc.ExitCode))" }
  Info "Monitor up (pid $($monProc.Id))."

  $dups = @(Find-Runners)
  if ($dups.Count -gt 0) { Fail ("controller appeared before start:`n  " + ($dups -join "`n  ")) }
  # A stale heartbeat from a killed run would confuse the wait below; with no
  # live runner proven above, removing it is safe (the runner rewrites it).
  $beat = Join-Path $VRoot "results\_runner.json"
  if (Test-Path $beat) { Remove-Item $beat -Force }
  Info "Starting $Version controller..."
  $runProc = Start-Process -FilePath $Py `
    -ArgumentList "-u", "versions/$Version/pilot/runner.py" `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $runOut -RedirectStandardError $runErr `
    -WindowStyle Hidden -PassThru
  $startedRunner = $true

  # ---- supervised wait for the first beat ----------------------------------
  $t0 = Get-Date
  $ready = $false
  $realPid = $null
  $lastNote = $t0.AddSeconds(-10)
  while (((Get-Date) - $t0).TotalSeconds -lt $BeatTimeoutSec) {
    Start-Sleep -Milliseconds 500
    $runProc.Refresh()
    if ($runProc.HasExited) { break }
    $hb = Get-HeartbeatAge $beat
    if ($hb.age -ne $null -and $hb.age -lt 5) { $ready = $true; break }
    # The venv python is a shim that spawns the real interpreter; the heartbeat
    # reports the real pid, which is the process worth watching.
    if ($hb.content -ne $null -and $hb.content.pid -ne $null) { $realPid = $hb.content.pid }
    if (((Get-Date) - $lastNote).TotalSeconds -ge 10) {
      $lastNote = Get-Date
      $ageTxt = if ($hb.age -eq $null) { "no file yet" } else { "age $([math]::Round($hb.age, 1))s" }
      $who = if ($realPid -ne $null) { "runner($realPid)" } else { "launcher-child" }
      try {
        $watched = if ($realPid -ne $null) { Get-Process -Id $realPid -ErrorAction Stop } else { $runProc }
        $cpu = [math]::Round($watched.CPU, 1)
      } catch { $cpu = "?" }
      $tail = ""
      if (Test-Path $runOut) {
        $tail = (Get-Content $runOut -Tail 2 -ErrorAction SilentlyContinue) -join " / "
      }
      Info ("waiting for beat: {0:N0}s elapsed, {1} cpu {2}s, heartbeat {3} :: {4}" -f `
        ((Get-Date) - $t0).TotalSeconds, $who, $cpu, $ageTxt, $tail)
    }
  }
  $incident["beat_wait_s"] = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
  if (-not $ready) {
    $runProc.Refresh()
    $incident["runner_exited"] = $runProc.HasExited
    try { $incident["runner_exit_code"] = $runProc.ExitCode } catch {}
    try { $incident["runner_cpu_s"] = [math]::Round($runProc.CPU, 1) } catch {}
    $hb = Get-HeartbeatAge $beat
    $incident["heartbeat_age_s"] = $hb.age
    Info "--- runner stdout tail ---"
    if (Test-Path $runOut) { Get-Content $runOut -Tail 30 | Write-Host }
    Info "--- runner stderr tail ---"
    if ((Test-Path $runErr) -and ((Get-Item $runErr).Length -gt 0)) {
      Get-Content $runErr -Tail 30 | Write-Host
    } else {
      Info "(empty)"
    }
    if ($runProc.HasExited) {
      Fail "runner exited during startup (code $($runProc.ExitCode)); output above"
    } else {
      Fail "runner alive but produced no fresh heartbeat in ${BeatTimeoutSec}s; output above"
    }
  }
  Info "Controller up (pid $($runProc.Id)), heartbeat fresh."

  # ---- one attempt (foreground) --------------------------------------------
  $monProc.Refresh()
  if ($monProc.HasExited) { Info "WARNING: monitor died before the attempt." }
  Info "Flying one $Split attempt ($Course)..."
  & $Py (Join-Path $Root "flightops\attempts.py") run --version $Version `
    --course $Course --split $Split --n 1 @setArgs --label $Label --timeout $Timeout
  if ($LASTEXITCODE -ne 0) { Fail "attempt failed (exit $LASTEXITCODE)" }
  $monProc.Refresh()
  if ($monProc.HasExited) {
    Info "WARNING: monitor died during the attempt; its partial output is kept."
  }

  # ---- wait for the monitor report ------------------------------------------
  $logsDir = Join-Path $VRoot "logs"
  $deadline = (Get-Date).AddSeconds(180)
  $sealed = $false
  while ((Get-Date) -lt $deadline) {
    $newest = Get-ChildItem $logsDir -Directory -Filter "*_gate_live" |
      Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $sum = Join-Path $MonLog "summary.csv"
    if ($newest -and (Test-Path $sum)) {
      $rows = Import-Csv $sum | Where-Object { $_.log -eq $newest.Name }
      if ($rows) {
        $sealed = $true
        $rows | Format-Table | Out-String | Write-Host
        break
      }
    }
    Start-Sleep -Seconds 2
  }
  if (-not $sealed) { Info "WARNING: no monitor row for the latest log yet." }
  $incident["sealed"] = $sealed
  Info "Done. Reports: $MonLog ; child output: $DiagDir"
  Write-Incident "ok"
} catch {
  Write-Host $_.Exception.Message -ForegroundColor Red
  try { Write-Incident ("failed: " + $_.Exception.Message) } catch {}
  exit 1
} finally {
  if (($startedMonitor -or $startedRunner) -and -not $KeepAlive -and -not $DryRun) { Stop-Stack }
}

if ($KeepAlive -and ($startedMonitor -or $startedRunner)) {
  $m = if ($monProc -and -not $monProc.HasExited) { "monitor pid $($monProc.Id)" } else { "monitor stopped" }
  $r = if ($runProc -and -not $runProc.HasExited) { "runner pid $($runProc.Id)" } else { "runner stopped" }
  Info "Stack left running: $m, $r. Stop the runner with job.py quit and the monitor with Stop-Process."
}
