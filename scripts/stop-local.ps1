# Stops the election system: the watchdog window of "1. Start.bat", the API and the UI.
# Run from the project root:   powershell -ExecutionPolicy Bypass -File scripts\stop-local.ps1
#   -Quiet   no messages (used by start-local.ps1 and install.ps1)

param([switch]$Quiet)

$root = Split-Path -Parent $PSScriptRoot
. "$PSScriptRoot\common.ps1"
$script:stopped = 0

function Say([string]$text, [string]$color = "Gray") { if (-not $Quiet) { Write-Host $text -ForegroundColor $color } }

function Stop-Tree([int]$processId, [string]$what) {
    if ($processId -le 4 -or $processId -eq $PID) { return }
    # /T also ends child processes (cmd + python, cmd + node)
    taskkill /PID $processId /T /F *> $null
    if ($LASTEXITCODE -eq 0) {
        Say "    stopped $what (PID $processId)" "Yellow"
        $script:stopped++
    }
}

# 1. The watchdog first, otherwise it would start the servers again
Say "==> Stopping the watchdog and the servers" "Cyan"
$stateFile = Join-Path $root "data\run\supervisor.json"
$state = $null
if (Test-Path $stateFile) { try { $state = Get-Content $stateFile -Raw | ConvertFrom-Json } catch { } }
Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe' OR Name = 'pwsh.exe'" |
    Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and (
        ($_.CommandLine -like "*start-local.ps1*" -and ($_.CommandLine -like "*$root*" -or ($state -and $_.ProcessId -eq $state.supervisor))) -or
        $_.CommandLine -like "*$root\icbOfficerAssoAPI*" -or $_.CommandLine -like "*$root\icbOfficerAssoUI*") } |
    ForEach-Object { Stop-Tree $_.ProcessId "watchdog / server window" }
if ($state) {
    foreach ($id in $state.api, $state.ui) {
        # only if that PID still is one of our servers (PIDs are reused by Windows)
        $p = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$id)" -ErrorAction SilentlyContinue
        if ($p -and $p.CommandLine -like "*$root*") { Stop-Tree $p.ProcessId "server" }
    }
}
Remove-Item $stateFile -Force -ErrorAction SilentlyContinue

# 2. Anything still listening on the API / UI ports (e.g. started by hand)
foreach ($port in 8000, 3000) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object { Stop-Tree $_ "process on port $port" }
}

Say ""
if ($script:stopped -gt 0) {
    Say "The election system is stopped. Everything saved stays in the database (data\)." "Green"
} else {
    Say "Nothing was running." "Green"
}
