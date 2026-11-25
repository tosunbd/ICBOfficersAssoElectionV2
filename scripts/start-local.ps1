# Starts the election system and keeps it running (Windows, no Docker).
# Used by "1. Start.bat":   powershell -ExecutionPolicy Bypass -File scripts\start-local.ps1 -Production
#
#   -Production   the way the election is run: the API and the optimised UI are
#                 started in the background and this window becomes their
#                 WATCHDOG for as long as it is open:
#                   * shows the addresses (this PC and the intranet),
#                   * checks both servers every few seconds and starts a server
#                     again by itself if it stopped or does not answer,
#                   * keeps the laptop from going to sleep,
#                   * warns when the laptop runs on battery or its address changes.
#                 Logs: data\logs.   Stop with "2. Stop.bat".
#   -Rebuild      with -Production: always rebuild the UI first
#   (neither)     developer mode: two windows with auto-reload, no watchdog
#
# Both servers listen on every network card (0.0.0.0): the UI on port 3000, the
# API on port 8000.  '0. install.bat' opens these ports in the firewall and, when
# IIS is available, also publishes the system on port 80.

param(
    [switch]$Production,
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$api = "$root\icbOfficerAssoAPI"
$ui = "$root\icbOfficerAssoUI"
$apiPort = 8000
$uiPort = 3000
. "$PSScriptRoot\common.ps1"

# ------------------------------------------------------------------ checks
$venvPython = "$api\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "The system is not installed on this PC yet. Run '0. install.bat' first." }
# A .venv copied from another PC starts but then fails inside uvicorn
$ErrorActionPreference = "Continue"
& $venvPython -c "import pydantic_core._pydantic_core, fastapi, sqlalchemy" 2>$null
$venvWorks = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"
if (-not $venvWorks) {
    throw "The API's Python packages do not work on this PC (icbOfficerAssoAPI\.venv was probably copied from another computer). Run '0. install.bat' - it builds a new .venv for this PC."
}
Use-ProjectRuntime $root | Out-Null
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node -or -not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Node.js was not found. Run '0. install.bat' first." }
if (-not (Test-Path "$ui\node_modules\next\dist\bin\next")) { throw "UI packages are missing. Run '0. install.bat' first." }

$basePath = "$((Read-DotEnv "$root\.env")['NEXT_PUBLIC_BASE_PATH'])".TrimEnd("/")
$env:NEXT_PUBLIC_BASE_PATH = $basePath
$env:NEXT_TELEMETRY_DISABLED = "1"

# ---------------------------------------------------------- developer mode
if (-not $Production) {
    Write-Host "==> Starting API on http://0.0.0.0:$apiPort  (docs: http://localhost:$apiPort/docs)" -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$api'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port $apiPort --reload"
    Write-Host "==> Starting UI on http://0.0.0.0:$uiPort$basePath" -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$ui'; npm run dev -- --hostname 0.0.0.0 --port $uiPort"
    Write-Host "Admin panel: http://localhost:$uiPort$basePath/admin    Dashboard: http://localhost:$uiPort$basePath/dashboard" -ForegroundColor Green
    return
}

# ===================================================================== run
$runDir = Join-Path $root "data\run"
$logDir = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force -Path $runDir, $logDir | Out-Null
$stateFile = Join-Path $runDir "supervisor.json"
$superLog = Join-Path $logDir "watchdog.log"

function Write-Event([string]$message, [string]$color = "Gray") {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $message"
    Write-Host $line -ForegroundColor $color
    try { Add-Content -Path $superLog -Value $line -Encoding UTF8 } catch { }
}

# Already running with a live watchdog: show the addresses, change nothing.
$previous = $null
if (Test-Path $stateFile) { try { $previous = Get-Content $stateFile -Raw | ConvertFrom-Json } catch { } }
if ($previous -and $previous.supervisor -and (Get-Process -Id $previous.supervisor -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '^(powershell|pwsh)$' })) {
    Write-Host ""
    Write-Host "The election system is ALREADY RUNNING (its window with the watchdog is open)." -ForegroundColor Green
    Show-Addresses -UiPort $uiPort -BasePath $basePath
    Write-Host "To restart it: run '2. Stop.bat', then '1. Start.bat'." -ForegroundColor Yellow
    return
}
# Servers left over without a watchdog (its window was closed): start clean.
& "$PSScriptRoot\stop-local.ps1" -Quiet

Invoke-UiBuild $root -Force:$Rebuild

# ------------------------------------------------------- this window
$Host.UI.RawUI.WindowTitle = "ICB Election System - RUNNING (do not close)"
# Keep the PC awake while this window lives, and do not let a click inside the
# window ("QuickEdit" selection) or Ctrl+C freeze or end the watchdog.
$awake = $false
try {
    Add-Type -Namespace Icb -Name Win -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);
[DllImport("kernel32.dll")] public static extern IntPtr GetStdHandle(int nStdHandle);
[DllImport("kernel32.dll")] public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);
[DllImport("kernel32.dll")] public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
'@
    $awake = $true
    $stdin = [Icb.Win]::GetStdHandle(-10)
    $mode = 0
    if ([Icb.Win]::GetConsoleMode($stdin, [ref]$mode)) {
        [Icb.Win]::SetConsoleMode($stdin, ($mode -band (-bnot 0x0040)) -bor 0x0080) | Out-Null   # QuickEdit off
    }
} catch { }
try { [Console]::TreatControlCAsInput = $true } catch { }
function Stay-Awake {
    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED: no automatic sleep while the count runs
    if ($awake) { try { [Icb.Win]::SetThreadExecutionState([uint32]"0x80000001") | Out-Null } catch { } }
}

# ------------------------------------------------------------ the servers
$servers = @(
    @{
        Name = "API"; Port = $apiPort; Dir = $api; Log = (Join-Path $logDir "api.log")
        Command = "`"$venvPython`" -m uvicorn app.main:app --host 0.0.0.0 --port $apiPort --no-access-log"
        Health = "http://127.0.0.1:$apiPort/api/health"
        Process = $null; Failures = 0; Restarts = 0; StartedAt = $null
    },
    @{
        Name = "UI"; Port = $uiPort; Dir = $ui; Log = (Join-Path $logDir "ui.log")
        Command = "`"$($node.Source)`" `"$ui\node_modules\next\dist\bin\next`" start --hostname 0.0.0.0 --port $uiPort"
        Health = "http://127.0.0.1:$uiPort$basePath/favicon.svg"
        Process = $null; Failures = 0; Restarts = 0; StartedAt = $null
    }
)
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONUTF8 = "1"
$env:NODE_ENV = "production"

function Save-State {
    @{ supervisor = $PID; api = $servers[0].Process.Id; ui = $servers[1].Process.Id; started = (Get-Date).ToString("s") } |
        ConvertTo-Json | Set-Content $stateFile -Encoding ASCII
}

function Start-Server($server) {
    Stop-PortOwners $server.Port
    # a log never grows without end: the previous one is kept as *.old.log
    if ((Test-Path $server.Log) -and (Get-Item $server.Log).Length -gt 20MB) {
        Move-Item $server.Log ($server.Log -replace '\.log$', '.old.log') -Force
    }
    Add-Content -Path $server.Log -Value "`r`n===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') starting $($server.Name) =====" -Encoding ASCII
    # hidden, output to the log file: nothing on a screen can block or close the server
    $line = "/d /s /c `"$($server.Command) >> `"$($server.Log)`" 2>&1`""
    $server.Process = Start-Process -FilePath $env:ComSpec -ArgumentList $line -WorkingDirectory $server.Dir -WindowStyle Hidden -PassThru
    $server.StartedAt = Get-Date
    $server.Failures = 0
    Save-State
}

function Wait-Server($server, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if ($server.Process.HasExited) { return $false }
        if (Test-Url $server.Health) { return $true }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

Write-Host ""
Write-Event "Starting the election system" "Cyan"
foreach ($server in $servers) {
    Start-Server $server
    if (Wait-Server $server 90) {
        Write-Event "$($server.Name) is running (port $($server.Port))" "Green"
    } else {
        Write-Event "$($server.Name) did NOT start. Last lines of $($server.Log):" "Red"
        Get-Content $server.Log -Tail 25 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        & "$PSScriptRoot\stop-local.ps1" -Quiet
        throw "$($server.Name) could not be started. Fix the problem shown above (or run '0. install.bat' again) and start again."
    }
}

Show-Addresses -UiPort $uiPort -BasePath $basePath
if (-not (Test-FirewallOpen $uiPort) -or -not (Test-FirewallOpen $apiPort)) {
    Write-Host "NOTE: Windows Firewall has no rule for ports $uiPort and ${apiPort}: other PCs may not get through." -ForegroundColor Yellow
    Write-Host "      Run '0. install.bat' once on this PC (it opens them)." -ForegroundColor Yellow
}
Write-Host "Logins: SA / sadmin, Admin / admin, EC1 / EC1, EC2 / EC2, EC3 / EC3 (change them under Settings)" -ForegroundColor Gray
Write-Host ""
Write-Host "KEEP THIS WINDOW OPEN during the election: it watches both servers, restarts one" -ForegroundColor White
Write-Host "that stops, and keeps this PC awake.  Keep the laptop on mains power." -ForegroundColor White
Write-Host "To stop the system: '2. Stop.bat'.   Logs: data\logs   Backups: data\Backups" -ForegroundColor White
Write-Host ""

# ------------------------------------------------------------ the watchdog
$startedAt = Get-Date
$addresses = (Get-LanAddresses) -join ","
$lastHealth = Get-Date
$lastStatus = Get-Date
$lastPower = ""
while ($true) {
    Start-Sleep -Seconds 3
    Stay-Awake
    try {
        $checkHealth = ((Get-Date) - $lastHealth).TotalSeconds -ge 12
        if ($checkHealth) { $lastHealth = Get-Date }
        foreach ($server in $servers) {
            $why = $null
            if ($server.Process.HasExited) { $why = "stopped unexpectedly" }
            elseif ($checkHealth) {
                if (Test-Url $server.Health) { $server.Failures = 0 } else { $server.Failures++ }
                if ($server.Failures -ge 3) { $why = "does not answer" }
            }
            if ($why) {
                $server.Restarts++
                Write-Event "$($server.Name) $why - starting it again (restart no. $($server.Restarts))" "Yellow"
                try { taskkill /PID $server.Process.Id /T /F *> $null } catch { }
                Start-Server $server
                if (Wait-Server $server 90) { Write-Event "$($server.Name) is running again. Nothing saved was lost; the screens reconnect by themselves." "Green" }
                else { Write-Event "$($server.Name) is still not answering - trying again. See $($server.Log)" "Red" }
            }
        }

        # the laptop moved to another network / got another address
        $now = (Get-LanAddresses) -join ","
        if ($now -ne $addresses) {
            $addresses = $now
            Write-Event "The network address of this PC changed. The other PCs must use the new address:" "Yellow"
            Show-Addresses -UiPort $uiPort -BasePath $basePath
        }

        $power = Get-PowerState
        if ($power.Text -ne $lastPower) {
            if ($power.OnBattery) { Write-Event "WARNING: the laptop runs on BATTERY ($($power.Percent)%). Plug in the charger." "Red" }
            elseif ($lastPower) { Write-Event "Mains power is back." "Green" }
            $lastPower = $power.Text
        }

        $up = (Get-Date) - $startedAt
        $upText = "{0}h {1:00}m" -f [int][math]::Floor($up.TotalHours), $up.Minutes
        $Host.UI.RawUI.WindowTitle = "ICB Election System - RUNNING $upText (do not close)"
        if (((Get-Date) - $lastStatus).TotalMinutes -ge 15) {
            $lastStatus = Get-Date
            $restarts = ($servers | ForEach-Object { $_.Restarts } | Measure-Object -Sum).Sum
            Write-Event "OK - running for $upText, API and UI answer, restarts: $restarts, power: $($power.Text)" "DarkGray"
        }
    } catch {
        Write-Event "Watchdog: $($_.Exception.Message)" "DarkYellow"
    }
}
