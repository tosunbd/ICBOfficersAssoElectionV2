# Installs everything the election system needs on this Windows PC and
# publishes it on the LAN through IIS.  Started by '0. install.bat' (as
# administrator); safe to run again - finished steps are skipped.
#
#   1. Python <PythonVersion> (64-bit) - an installed copy is used if found,
#      otherwise the latest <PythonVersion>.x is installed into
#      <PythonInstallDir> without touching other Python versions
#   2. API packages in icbOfficerAssoAPI\.venv - rebuilt when it was copied
#      from another PC or made with another Python
#   3. Node.js >= <NodeMinVersion> - the one on PATH if new enough, otherwise
#      the current LTS is unpacked into tools\node (nothing system-wide)
#   4. UI packages + production build (served under <IisAppPath>)
#   5. Windows Firewall rules so other PCs on the intranet reach this one:
#      port 3000 (the pages), 8000 (API / live stream) and 80 (IIS)
#   6. Laptop power settings: no sleep on mains power, closing the lid does
#      nothing (the count must not stop because the lid was closed)
#   7. IIS (+ URL Rewrite, Application Request Routing) with an application
#      <IisSite><IisAppPath> that forwards to the API (:8000) and UI (:3000).
#      Optional extra: when IIS cannot be set up the installation still
#      succeeds and the system is used on port 3000.
#
# Afterwards start the system with "1. Start.bat".

param(
    [string]$PythonVersion = "3.14",
    [string]$PythonInstallDir = "C:\Python\Python314",
    [string]$NodeMinVersion = "20.9.0",
    [string]$IisSite = "Default Web Site",
    [string]$IisAppPath = "/election",
    [switch]$SkipIis,
    [switch]$RecreateVenv,
    [switch]$SkipPowerSettings
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is very slow with the progress bar
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$root = Split-Path -Parent $PSScriptRoot
. "$PSScriptRoot\common.ps1"
$tools = Join-Path $root "tools"
$downloads = Join-Path $tools "downloads"
New-Item -ItemType Directory -Force -Path $downloads | Out-Null

$IisAppPath = "/" + $IisAppPath.Trim("/")
$apiPort = 8000
$uiPort = 3000

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "Run '0. install.bat' as administrator (it is needed for IIS, the firewall and the Python installer)." }

# A running system would lock the files that are replaced below
& "$PSScriptRoot\stop-local.ps1" -Quiet

function Save-Download([string]$url, [string]$fileName) {
    $target = Join-Path $downloads $fileName
    if (Test-Path $target) { return $target }
    Write-Host "    downloading $url"
    # Download servers sometimes answer with a passing error (400/5xx): try a few times
    for ($attempt = 1; ; $attempt++) {
        try {
            Invoke-WebRequest -Uri $url -OutFile "$target.part" -UseBasicParsing
            break
        } catch {
            Remove-Item "$target.part" -Force -ErrorAction SilentlyContinue
            if ($attempt -ge 4) {
                throw "Download failed after $attempt attempts: $url - $($_.Exception.Message) (check the internet connection, or download the file yourself into $target)"
            }
            Write-Host "    attempt $attempt failed ($($_.Exception.Message)) - retrying in $($attempt * 5) s" -ForegroundColor Yellow
            Start-Sleep -Seconds ($attempt * 5)
        }
    }
    Move-Item "$target.part" $target -Force
    return $target
}

function Install-Msi([string]$msi, [string]$what) {
    Write-Host "    installing $what"
    $p = Start-Process msiexec.exe -ArgumentList "/i", "`"$msi`"", "/qn", "/norestart" -Wait -PassThru
    if ($p.ExitCode -notin 0, 3010) { throw "$what installer failed (exit code $($p.ExitCode))" }
}

# ----------------------------------------------------------------- 1. Python
# "3.14 64" when $exe is a working 64-bit Python of the wanted version.
function Test-Python([string]$exe) {
    # Windows PowerShell turns a native program's stderr into errors under "Stop"
    $ErrorActionPreference = "Continue"
    if (-not $exe -or -not (Test-Path $exe) -or $exe -like "*\WindowsApps\*") { return $false }
    try {
        $out = & $exe -c "import sys, struct; print('%d.%d %d' % (sys.version_info[0], sys.version_info[1], struct.calcsize('P') * 8))" 2>$null
        return ("$out".Trim() -eq "$PythonVersion 64")
    } catch { return $false }
}

function Find-Python {
    $ErrorActionPreference = "Continue"
    $candidates = New-Object System.Collections.Generic.List[string]
    # The folder named in '0. install.bat' comes first
    $candidates.Add((Join-Path $PythonInstallDir "python.exe"))
    # Registered installations (python.org installers, per-user and all-users)
    foreach ($hive in "HKCU:", "HKLM:") {
        $key = "$hive\SOFTWARE\Python\PythonCore\$PythonVersion\InstallPath"
        $item = Get-ItemProperty $key -ErrorAction SilentlyContinue
        if ($item) {
            if ($item.ExecutablePath) { $candidates.Add($item.ExecutablePath) }
            if ($item.'(default)') { $candidates.Add((Join-Path $item.'(default)' "python.exe")) }
        }
    }
    # The py launcher, then every python.exe on PATH
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $fromPy = & py "-$PythonVersion" -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $fromPy) { $candidates.Add("$fromPy".Trim()) }
    }
    Get-Command python -All -ErrorAction SilentlyContinue | ForEach-Object { $candidates.Add($_.Source) }

    foreach ($exe in $candidates) {
        if (Test-Python $exe) { return (Resolve-Path $exe).Path }
    }
    return $null
}

function Install-Python {
    Write-Host "    looking up the latest Python $PythonVersion.x release"
    $listing = (Invoke-WebRequest -Uri "https://www.python.org/ftp/python/" -UseBasicParsing).Content
    $versions = [regex]::Matches($listing, "href=`"($([regex]::Escape($PythonVersion))\.\d+)/`"") |
        ForEach-Object { $_.Groups[1].Value } | Sort-Object { [version]$_ } -Descending -Unique
    $installer = $null
    foreach ($v in $versions) {
        # Newest folders can exist before their installer is published
        $url = "https://www.python.org/ftp/python/$v/python-$v-amd64.exe"
        try {
            Invoke-WebRequest -Uri $url -Method Head -UseBasicParsing | Out-Null
            $installer = Save-Download $url "python-$v-amd64.exe"
            break
        } catch { continue }
    }
    if (-not $installer) { throw "Could not find a Python $PythonVersion installer on python.org" }

    # Own folder, no PATH change, no file associations, no py launcher change:
    # other Python versions on this PC keep working exactly as before.
    Write-Host "    installing $(Split-Path $installer -Leaf) into $PythonInstallDir"
    $arguments = @(
        "/quiet", "InstallAllUsers=1", "TargetDir=`"$PythonInstallDir`"", "PrependPath=0",
        "AssociateFiles=0", "Shortcuts=0", "Include_launcher=0", "Include_test=0",
        "Include_doc=0", "Include_tcltk=0"
    )
    $p = Start-Process $installer -ArgumentList $arguments -Wait -PassThru
    if ($p.ExitCode -notin 0, 3010) { throw "Python installer failed (exit code $($p.ExitCode))" }
}

Write-Host "==> Python $PythonVersion" -ForegroundColor Cyan
$python = Find-Python
if ($python) {
    Write-Host "    found $python"
} else {
    Write-Host "    not installed - installing it"
    Install-Python
    $python = Find-Python
    if (-not $python) { throw "Python $PythonVersion was installed but cannot be found in $PythonInstallDir" }
    Write-Host "    installed $python"
}

# ------------------------------------------------------------- 2. API packages
Write-Host "==> Backend packages (icbOfficerAssoAPI\.venv)" -ForegroundColor Cyan
$api = Join-Path $root "icbOfficerAssoAPI"
$venv = Join-Path $api ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
# A .venv only works on the PC (and the Python) that created it: one copied
# from another computer fails with errors such as
# "No module named 'pydantic_core._pydantic_core'".  The marker file records
# where it was made; anything else is thrown away and built fresh.
$venvMarker = Join-Path $venv "icb-created-for.txt"
$venvOwner = "$env:COMPUTERNAME|$python"
$recreate = $null
if ($RecreateVenv) { $recreate = "a fresh one was requested (RECREATE_VENV=yes)" }
elseif ((Test-Path $venv) -and -not (Test-Python $venvPython)) { $recreate = "it does not run Python $PythonVersion" }
elseif ((Test-Path $venv) -and (-not (Test-Path $venvMarker) -or (Get-Content $venvMarker -Raw).Trim() -ne $venvOwner)) { $recreate = "it was made on another PC or with another Python" }
if ($recreate) {
    Write-Host "    removing the existing .venv: $recreate" -ForegroundColor Yellow
    Remove-Item $venv -Recurse -Force
}
if (-not (Test-Path $venvPython)) {
    Write-Host "    creating a new .venv with $python"
    & $python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment" }
    Set-Content -Path $venvMarker -Value $venvOwner -Encoding ASCII
}
& $venvPython -m pip install --upgrade pip --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $venvPython -m pip install -r (Join-Path $api "requirements-dev.txt") --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "Installing the API packages failed" }
& $venvPython -c "import pydantic_core._pydantic_core, fastapi, uvicorn, sqlalchemy, aiosqlite, sse_starlette, multipart, jose, bcrypt"
if ($LASTEXITCODE -ne 0) { throw "The API packages do not load - set RECREATE_VENV=yes in '0. install.bat' and run it again" }
Write-Host "    API packages load correctly"

# ------------------------------------------------------------------ 3. Node.js
function Get-NodeVersion([string]$exe) {
    $ErrorActionPreference = "Continue"
    try {
        $out = & $exe --version 2>$null
        if ("$out" -match '^v(\d+\.\d+\.\d+)') { return [version]$Matches[1] }
    } catch { }
    return $null
}

Write-Host "==> Node.js >= $NodeMinVersion" -ForegroundColor Cyan
$nodeDir = $null
$localNode = Join-Path $tools "node\node.exe"
$systemNode = Get-Command node -ErrorAction SilentlyContinue
if ($systemNode -and (Get-NodeVersion $systemNode.Source) -ge [version]$NodeMinVersion) {
    $nodeDir = Split-Path $systemNode.Source
    Write-Host "    found $($systemNode.Source) (v$(Get-NodeVersion $systemNode.Source))"
} elseif ((Test-Path $localNode) -and (Get-NodeVersion $localNode) -ge [version]$NodeMinVersion) {
    $nodeDir = Split-Path $localNode
    Write-Host "    found $localNode (v$(Get-NodeVersion $localNode))"
} else {
    if ($systemNode) { Write-Host "    $($systemNode.Source) is too old (v$(Get-NodeVersion $systemNode.Source)) - it is left as it is" }
    Write-Host "    installing the current Node.js LTS into tools\node (for this project only)"
    # Assign first: Windows PowerShell 5.1 passes Invoke-RestMethod's JSON array
    # down a pipeline as ONE object, so filtering it directly picks the whole list
    $releases = Invoke-RestMethod "https://nodejs.org/dist/index.json"
    $release = @($releases) | ForEach-Object { $_ } |
        Where-Object { $_.lts -and @($_.files) -contains "win-x64-zip" } | Select-Object -First 1
    $v = "$($release.version)"
    if ($v -notmatch '^v\d+\.\d+\.\d+$') { throw "Could not find the current Node.js LTS version on nodejs.org (got '$v')" }
    $zipName = "node-$v-win-x64.zip"
    $zip = Save-Download "https://nodejs.org/dist/$v/$zipName" $zipName
    $sums = (Invoke-WebRequest -Uri "https://nodejs.org/dist/$v/SHASUMS256.txt" -UseBasicParsing).Content
    $expected = ([regex]::Match($sums, "([0-9a-f]{64})\s+$([regex]::Escape($zipName))")).Groups[1].Value
    if ((Get-FileHash $zip -Algorithm SHA256).Hash -ne $expected.ToUpper()) {
        Remove-Item $zip -Force
        throw "Checksum mismatch for $zipName - run '0. install.bat' again"
    }
    $unpack = Join-Path $tools "node-unpack"
    Remove-Item $unpack, (Join-Path $tools "node") -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive $zip -DestinationPath $unpack
    Move-Item (Join-Path $unpack "node-$v-win-x64") (Join-Path $tools "node")
    Remove-Item $unpack -Recurse -Force
    $nodeDir = Split-Path $localNode
    Write-Host "    installed $localNode ($v)"
}

@{ python = $python; venvPython = $venvPython; nodeDir = $nodeDir } |
    ConvertTo-Json | Set-Content (Join-Path $tools "runtime.json") -Encoding ASCII
$env:Path = "$nodeDir;$env:Path"

# ------------------------------------------------------- 4. Settings + the UI
Set-Location $root
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "==> Created .env from .env.example (edit it to change passwords/folders)" -ForegroundColor Yellow
}
# The UI's URL prefix must match the IIS application path
$basePath = if ($SkipIis) { "" } else { $IisAppPath }
$envLines = @(Get-Content ".env" -Encoding UTF8)
if ($envLines -match '^NEXT_PUBLIC_BASE_PATH=') {
    $envLines = $envLines -replace '^NEXT_PUBLIC_BASE_PATH=.*$', "NEXT_PUBLIC_BASE_PATH=$basePath"
} else {
    $envLines += "NEXT_PUBLIC_BASE_PATH=$basePath"
}
# A secret of its own for this PC (signs the logins); the sample value is never kept
if (-not ($envLines -match '^JWT_SECRET_KEY=') -or ($envLines -match '^JWT_SECRET_KEY=\s*(change-me.*)?$')) {
    $bytes = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secret = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    if ($envLines -match '^JWT_SECRET_KEY=') { $envLines = $envLines -replace '^JWT_SECRET_KEY=.*$', "JWT_SECRET_KEY=$secret" }
    else { $envLines += "JWT_SECRET_KEY=$secret" }
    Write-Host "==> Created a login secret for this PC (JWT_SECRET_KEY in .env)" -ForegroundColor Cyan
}
[IO.File]::WriteAllLines((Join-Path $root ".env"), [string[]]$envLines, (New-Object Text.UTF8Encoding($false)))

foreach ($d in @("data", "data\logs", "data\Backups")) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

Write-Host "==> Frontend packages (icbOfficerAssoUI\node_modules)" -ForegroundColor Cyan
Push-Location (Join-Path $root "icbOfficerAssoUI")
npm install --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm install failed" }
Pop-Location
Invoke-UiBuild $root

# ---------------------------------------------------------------- 5. Firewall
# 3000 = the pages, 8000 = the API and the live screen's event stream (the
# browsers of the other PCs open both), 80 = the same pages through IIS
Write-Host "==> Windows Firewall: allowing ports $uiPort, $apiPort and 80 from the intranet" -ForegroundColor Cyan
foreach ($rule in @(
        @{ Name = "ICB Election System (pages $uiPort)"; Port = $uiPort },
        @{ Name = "ICB Election System (live stream $apiPort)"; Port = $apiPort },
        @{ Name = "ICB Election System (HTTP 80)"; Port = 80 })) {
    try {
        $existing = Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
        if (-not $existing) {
            New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Protocol TCP -LocalPort $rule.Port -Action Allow -Profile Any | Out-Null
            Write-Host "    added rule '$($rule.Name)'"
        } else {
            $existing | Set-NetFirewallRule -Enabled True -Action Allow -Profile Any
            Write-Host "    rule '$($rule.Name)' already exists"
        }
    } catch {
        Write-Host "    could not add the rule '$($rule.Name)': $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "    Other PCs may not reach this one until TCP port $($rule.Port) is allowed in the firewall." -ForegroundColor Yellow
    }
}

# ------------------------------------------------------------ 6. Power (laptop)
if (-not $SkipPowerSettings) {
    Write-Host "==> Power settings: no sleep on mains power, closing the lid does nothing" -ForegroundColor Cyan
    $ErrorActionPreference = "Continue"
    powercfg /change standby-timeout-ac 0 2>$null | Out-Null
    powercfg /change hibernate-timeout-ac 0 2>$null | Out-Null
    powercfg /change disk-timeout-ac 0 2>$null | Out-Null
    # lid close action: 0 = do nothing (mains and battery)
    powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0 2>$null | Out-Null
    powercfg /setdcvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0 2>$null | Out-Null
    powercfg /setactive SCHEME_CURRENT 2>$null | Out-Null
    $ErrorActionPreference = "Stop"
    Write-Host "    done (while the system runs, '1. Start.bat' also keeps the PC awake on battery)"
}

# --------------------------------------------------------------------- 7. IIS
$iisReady = $false
if (-not $SkipIis) {
    try {
        Write-Host "==> IIS: publishing http://<this-pc>$IisAppPath" -ForegroundColor Cyan
        $appcmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
        if (-not (Get-Service W3SVC -ErrorAction SilentlyContinue)) {
            Write-Host "    enabling the IIS web server (Windows feature)"
            Enable-WindowsOptionalFeature -Online -All -NoRestart -FeatureName IIS-WebServerRole, IIS-WebServer, IIS-RequestFiltering, IIS-ManagementConsole | Out-Null
        }

        $modulesAdded = $false
        if (-not (Test-Path (Join-Path $env:windir "System32\inetsrv\rewrite.dll"))) {
            Install-Msi (Save-Download "https://download.microsoft.com/download/1/2/8/128E2E22-C1B9-44A4-BE2A-5859ED1D4592/rewrite_amd64_en-US.msi" "rewrite_amd64_en-US.msi") "IIS URL Rewrite 2.1"
            $modulesAdded = $true
        } else { Write-Host "    URL Rewrite already installed" }
        if (-not (Test-Path (Join-Path $env:ProgramFiles "IIS\Application Request Routing\requestRouter.dll"))) {
            Install-Msi (Save-Download "https://download.microsoft.com/download/E/9/8/E9849D6A-020E-47E4-9FD0-A023E99B54EB/requestRouter_amd64.msi" "requestRouter_amd64.msi") "IIS Application Request Routing 3.0"
            $modulesAdded = $true
        } else { Write-Host "    Application Request Routing already installed" }

        function Invoke-AppCmd {
            $ErrorActionPreference = "Continue"
            $out = & $appcmd @args 2>&1
            if ($LASTEXITCODE -ne 0) { throw "appcmd $($args -join ' ') failed: $out" }
            return $out
        }
        # True when IIS has a site / apppool / app with exactly this name
        # ("appcmd list app <name>" also succeeds for names that do not exist).
        function Test-IisObject([string]$kind, [string]$name) {
            $ErrorActionPreference = "Continue"
            # <appcmd><APP APP.NAME="Default Web Site/election" .../></appcmd>
            [xml]$listing = (& $appcmd list $kind /xml 2>$null) -join "`n"
            $attribute = "$($kind.ToUpper()).NAME"
            return [bool]($listing.appcmd.ChildNodes | Where-Object { $_.GetAttribute($attribute) -ieq $name })
        }

        # Reverse proxy on (only rules that forward to another server use it, so
        # existing sites are unaffected); no response buffering so the live
        # screen's event stream reaches the browser at once.
        Invoke-AppCmd set config "-section:system.webServer/proxy" /enabled:"True" /responseBufferLimit:"0" /timeout:"00:05:00" /commit:apphost | Out-Null

        if (-not (Test-IisObject site $IisSite)) { throw "IIS site '$IisSite' does not exist - set IIS_SITE in '0. install.bat'" }

        # The application folder only holds web.config (the proxy rules)
        $appDir = Join-Path $env:SystemDrive "inetpub\icb-election"
        New-Item -ItemType Directory -Force -Path $appDir | Out-Null
        $config = (Get-Content (Join-Path $root "deploy\iis\web.config") -Raw).
            Replace("__API_PORT__", "$apiPort").Replace("__UI_PORT__", "$uiPort").Replace("__APP_PATH__", $IisAppPath)
        [IO.File]::WriteAllText((Join-Path $appDir "web.config"), $config, (New-Object Text.UTF8Encoding($false)))

        $pool = "ICBElection"
        if (-not (Test-IisObject apppool $pool)) {
            Invoke-AppCmd add apppool /name:"$pool" /managedRuntimeVersion:"" | Out-Null
            Write-Host "    created application pool $pool"
        }
        $appId = "$IisSite$IisAppPath"
        if (-not (Test-IisObject app $appId)) {
            Invoke-AppCmd add app /site.name:"$IisSite" /path:"$IisAppPath" /physicalPath:"$appDir" /applicationPool:"$pool" | Out-Null
            Write-Host "    created application $appId"
        } else {
            Invoke-AppCmd set app "$appId" /applicationPool:"$pool" | Out-Null
            Invoke-AppCmd set vdir "$appId/" /physicalPath:"$appDir" | Out-Null
            Write-Host "    updated application $appId"
        }
        # Ballot uploads can be large (default IIS limit is 30 MB)
        Invoke-AppCmd set config "$appId" "-section:system.webServer/security/requestFiltering" /requestLimits.maxAllowedContentLength:1073741824 /allowDoubleEscaping:"True" /commit:apphost | Out-Null

        if ($modulesAdded) {
            Write-Host "    restarting IIS to load the new modules"
            Restart-Service W3SVC -Force
        }
        if ((Get-Service W3SVC).Status -ne "Running") { Start-Service W3SVC }
        $iisReady = $true
    } catch {
        Write-Host "    IIS could not be set up: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "    This is not a problem: the system works without IIS on port $uiPort (addresses below)." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Installation complete.  Start the system with  1. Start.bat" -ForegroundColor Green
Write-Host "It will then be reached at:" -ForegroundColor Green
Write-Host "    On this PC:      http://localhost:$uiPort$basePath/admin      http://localhost:$uiPort$basePath/dashboard" -ForegroundColor Green
foreach ($ip in Get-LanAddresses) {
    Write-Host "    From other PCs:  http://${ip}:$uiPort$basePath/admin      http://${ip}:$uiPort$basePath/dashboard" -ForegroundColor Green
    if ($iisReady) { Write-Host "       (through IIS)  http://$ip$basePath/admin      http://$ip$basePath/dashboard" -ForegroundColor DarkGreen }
}
Write-Host "'1. Start.bat' shows these addresses again every time it starts." -ForegroundColor Green
