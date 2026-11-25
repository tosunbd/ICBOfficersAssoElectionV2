# Helpers shared by install.ps1 and start-local.ps1 (dot-source this file).

# KEY=VALUE pairs from a .env file; blank lines, "# comments" and trailing
# "   # notes" are ignored.
function Read-DotEnv([string]$path) {
    $values = @{}
    if (-not (Test-Path $path)) { return $values }
    foreach ($line in Get-Content $path -Encoding UTF8) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $key, $value = $line -split '=', 2
        $value = ($value -replace '\s+#.*$', '').Trim()
        $values[$key.Trim()] = $value
    }
    return $values
}

# Runtimes chosen by install.ps1 (tools\runtime.json): puts the Node.js folder
# first on PATH for this process and the windows it starts.
function Use-ProjectRuntime([string]$root) {
    $file = Join-Path $root "tools\runtime.json"
    if (-not (Test-Path $file)) { return $null }
    $runtime = Get-Content $file -Raw | ConvertFrom-Json
    if ($runtime.nodeDir -and (Test-Path $runtime.nodeDir)) {
        $env:Path = "$($runtime.nodeDir);$env:Path"
    }
    return $runtime
}

# IPv4 addresses other PCs on the LAN can use to reach this one.
function Get-LanAddresses {
    @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.InterfaceAlias -notlike 'vEthernet*' -and $_.InterfaceAlias -notlike '*Loopback*' -and $_.AddressState -eq 'Preferred' } |
        Select-Object -ExpandProperty IPAddress | Sort-Object -Unique)
}

# True when the URL answers (any status below 500) within the timeout.
function Test-Url([string]$url, [int]$timeoutMs = 5000) {
    $response = $null
    try {
        $request = [Net.HttpWebRequest]::Create($url)
        $request.Timeout = $timeoutMs
        $request.ReadWriteTimeout = $timeoutMs
        $request.Proxy = $null          # never through the office proxy
        $request.KeepAlive = $false
        $request.AllowAutoRedirect = $false
        $response = $request.GetResponse()
        return ([int]$response.StatusCode -lt 400)
    } catch {
        return $false
    } finally {
        if ($response) { $response.Close() }
    }
}

# Ends whatever listens on a TCP port (with its child processes).
function Stop-PortOwners([int]$port) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        Where-Object { $_ -gt 4 } |
        ForEach-Object { taskkill /PID $_ /T /F *> $null }
}

# True when an enabled inbound firewall rule of this system allows the port.
function Test-FirewallOpen([int]$port) {
    try {
        $rules = Get-NetFirewallRule -DisplayName "ICB Election System*" -ErrorAction SilentlyContinue | Where-Object { $_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound' }
        foreach ($rule in $rules) {
            if (($rule | Get-NetFirewallPortFilter).LocalPort -contains "$port") { return $true }
        }
        return $false
    } catch { return $true }   # cannot tell: do not alarm
}

# Mains / battery state of a laptop (a desktop PC is always "mains power").
function Get-PowerState {
    $state = @{ OnBattery = $false; Percent = $null; Text = "mains power" }
    try {
        $battery = Get-CimInstance Win32_Battery -ErrorAction Stop | Select-Object -First 1
        if ($battery) {
            $state.Percent = [int]$battery.EstimatedChargeRemaining
            # 1 = discharging, 4 / 5 = low / critical
            $state.OnBattery = ($battery.BatteryStatus -in 1, 4, 5)
            $state.Text = if ($state.OnBattery) { "BATTERY $([math]::Floor($state.Percent / 10) * 10)%" } else { "mains power" }
        }
    } catch { }
    return $state
}

# Prints where the system is reached: on this PC and from the intranet.
function Show-Addresses([int]$UiPort, [string]$BasePath) {
    $ips = Get-LanAddresses
    # also published by IIS on port 80 (set up by '0. install.bat')?
    $iis = $BasePath -and (Test-Url "http://127.0.0.1$BasePath/favicon.svg" 3000)
    Write-Host ""
    Write-Host "  ============================ ADDRESSES ============================" -ForegroundColor Green
    Write-Host "  On this PC (localhost)" -ForegroundColor White
    Write-Host "      Admin / ballot entry :  http://localhost:$UiPort$BasePath/admin" -ForegroundColor Green
    Write-Host "      Public dashboard     :  http://localhost:$UiPort$BasePath/dashboard" -ForegroundColor Green
    if ($ips.Count -eq 0) {
        Write-Host "  From other PCs: this PC has NO network address now (cable / Wi-Fi not connected)." -ForegroundColor Yellow
    }
    foreach ($ip in $ips) {
        Write-Host "  From other PCs on the intranet (IP address $ip)" -ForegroundColor White
        Write-Host "      Admin / ballot entry :  http://${ip}:$UiPort$BasePath/admin" -ForegroundColor Green
        Write-Host "      Public dashboard     :  http://${ip}:$UiPort$BasePath/dashboard" -ForegroundColor Green
        if ($iis) {
            Write-Host "      (also, through IIS)  :  http://$ip$BasePath/admin    http://$ip$BasePath/dashboard" -ForegroundColor DarkGreen
        }
    }
    if ($ips.Count -gt 0) {
        Write-Host "  By computer name (keeps working if the IP address changes)" -ForegroundColor White
        Write-Host "      http://$($env:COMPUTERNAME):$UiPort$BasePath/admin" -ForegroundColor Green
    }
    Write-Host "  ===================================================================" -ForegroundColor Green
    Write-Host ""
}

# Builds the UI (next build) when there is no build yet, a source file is newer
# than the last build, or NEXT_PUBLIC_BASE_PATH / NEXT_PUBLIC_API_URL changed
# (both are baked into the bundle).  -Force always rebuilds.
function Invoke-UiBuild([string]$root, [switch]$Force) {
    $ui = Join-Path $root "icbOfficerAssoUI"
    $envValues = Read-DotEnv (Join-Path $root ".env")
    $env:NEXT_PUBLIC_BASE_PATH = "$($envValues['NEXT_PUBLIC_BASE_PATH'])"
    $env:NEXT_PUBLIC_API_URL = "$($envValues['NEXT_PUBLIC_API_URL'])"
    $env:NEXT_TELEMETRY_DISABLED = "1"
    $wanted = "basePath=$env:NEXT_PUBLIC_BASE_PATH;apiUrl=$env:NEXT_PUBLIC_API_URL"

    $buildId = Join-Path $ui ".next\BUILD_ID"
    $stampFile = Join-Path $ui ".next\icb-build-stamp.txt"
    $reason = $null
    if ($Force) { $reason = "rebuild requested" }
    elseif (-not (Test-Path $buildId)) { $reason = "no build yet" }
    elseif (-not (Test-Path $stampFile) -or (Get-Content $stampFile -Raw).Trim() -ne $wanted) { $reason = "URL settings changed" }
    else {
        $builtAt = (Get-Item $buildId).LastWriteTime
        $sources = @(Get-ChildItem (Join-Path $ui "src"), (Join-Path $ui "public") -Recurse -File) +
                   @(Get-Item (Join-Path $ui "next.config.ts"), (Join-Path $ui "package.json"), (Join-Path $ui "package-lock.json"))
        if ($sources | Where-Object { $_.LastWriteTime -gt $builtAt } | Select-Object -First 1) { $reason = "source files changed" }
    }
    if (-not $reason) {
        Write-Host "    UI build is up to date" -ForegroundColor DarkGray
        return
    }

    Write-Host "==> Building UI ($reason) - this takes a minute" -ForegroundColor Cyan
    Push-Location $ui
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "UI build failed (npm run build exited with $LASTEXITCODE)" }
        Set-Content -Path $stampFile -Value $wanted -Encoding ASCII
    } finally {
        Pop-Location
    }
}
