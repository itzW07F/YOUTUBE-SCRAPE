#requires -Version 5.1
<#
.SYNOPSIS
  Production bootstrap for youtube-scrape on Windows (Python via uv, Node for GUI, Camoufox payload).

.DESCRIPTION
  - Verifies repository layout, disk space, and basic network reachability before heavy downloads.
  - Installs uv when missing; syncs Python from uv.lock; fetches Camoufox; runs npm ci in gui/.
  - Node.js: tries winget, then Chocolatey (if present), then a per-user portable LTS zip from nodejs.org
    (no admin required for the portable fallback).

.PARAMETER SkipGui
  Skip Electron dependency install (npm ci).

.PARAMETER SkipBrowser
  Skip python -m camoufox fetch.

.PARAMETER SkipPreflight
  Skip disk/network sanity checks (for automation only).

.PARAMETER MinDiskGiB
  Minimum free disk space on the repo drive (default 4).

.PARAMETER SkipAudit
  Skip the read-only environment audit banner (useful for CI or silent logs).

.EXAMPLE
  .\setup.ps1
.EXAMPLE
  .\setup-windows.cmd -SkipBrowser
#>
[CmdletBinding()]
param(
    [switch]$SkipGui,
    [switch]$SkipBrowser,
    [switch]$SkipPreflight,
    [switch]$SkipAudit,
    [int]$MinDiskGiB = 4
)

$ErrorActionPreference = "Stop"

if ($PSVersionTable.PSVersion.Major -lt 5 -or ($PSVersionTable.PSVersion.Major -eq 5 -and $PSVersionTable.PSVersion.Minor -lt 1)) {
    throw "Windows PowerShell 5.1 or PowerShell 7+ is required. Install latest PowerShell and rerun."
}

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {
    Write-Warning "Could not adjust TLS defaults; downloads may fail on older systems."
}

$PythonVersionPreferred = if ($env:PYTHON_VERSION) { $env:PYTHON_VERSION } else { "3.13" }
$MinimumNodeMajor = 18
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$GuiDir = Join-Path $RootDir "gui"
$PortableNodeRoot = Join-Path $env:LOCALAPPDATA "youtube-scrape-tools\nodejs-current"
$MaxAttempts = 4
$BaseDelaySec = 2

function Write-Phase {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Fatal {
    param([string]$Message)
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
}

function Sync-EnvironmentPath {
    <#
    Merges Machine + User PATH from the registry into this session so freshly installed tools resolve
    without requiring a brand-new terminal (best-effort; some installers still need a relaunch).
    #>
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $segments = @()
    foreach ($part in @($machine, $user)) {
        if ([string]::IsNullOrWhiteSpace($part)) { continue }
        foreach ($seg in $part -split ";") {
            $t = $seg.Trim()
            if ($t -and ($segments -notcontains $t)) {
                $segments += $t
            }
        }
    }
    foreach ($seg in ($env:Path -split ";")) {
        $t = $seg.Trim()
        if ($t -and ($segments -notcontains $t)) {
            $segments += $t
        }
    }
    $env:Path = ($segments -join ";")
}

function Add-LocalToolPaths {
    $paths = @(
        (Join-Path $env:USERPROFILE ".local\bin"),
        (Join-Path $env:USERPROFILE ".cargo\bin"),
        "C:\Program Files\nodejs",
        (Join-Path $env:ProgramFiles "nodejs"),
        (Join-Path ${env:ProgramFiles(x86)} "nodejs")
    )

    foreach ($path in $paths) {
        if ((Test-Path $path) -and (($env:Path -split ";") -notcontains $path)) {
            $env:Path = "$path;$env:Path"
        }
    }

    if ((Test-Path $PortableNodeRoot) -and (($env:Path -split ";") -notcontains $PortableNodeRoot)) {
        $env:Path = "$PortableNodeRoot;$env:Path"
    }
}

function Test-Command {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Assert-RepositoryLayout {
    $markers = @(
        (Join-Path $RootDir "uv.lock"),
        (Join-Path $RootDir "pyproject.toml"),
        (Join-Path $RootDir "gui\package-lock.json")
    )
    foreach ($m in $markers) {
        if (-not (Test-Path $m)) {
            throw "Missing required file: $m. Clone the full repository and run setup from its root (or run setup-windows.cmd from the repo folder)."
        }
    }
}

function Test-DiskSpace {
    param([int]$MinGiB)
    try {
        $driveName = (Resolve-Path $RootDir).Drive.Name
        $di = [System.IO.DriveInfo]::new("${driveName}:\")
        $need = [long]$MinGiB * 1024L * 1024L * 1024L
        if ($di.AvailableFreeSpace -lt $need) {
            throw "Insufficient free disk space on drive ${driveName}:. Need at least ${MinGiB} GiB for Python packages, Node modules, and Camoufox."
        }
    } catch {
        if ($_.Exception.Message -match "Insufficient free") { throw }
        Write-Warning "Could not verify free disk space; continuing. ($($_.Exception.Message))"
    }
}

function Test-NetworkReachability {
    $endpoints = @(
        "https://nodejs.org",
        "https://astral.sh"
    )
    foreach ($url in $endpoints) {
        try {
            Invoke-WebRequest -Uri $url -Method Head -UseBasicParsing -TimeoutSec 15 | Out-Null
        } catch {
            throw "Network check failed for $url. Confirm internet access, VPN/proxy, and TLS; then rerun. Details: $($_.Exception.Message)"
        }
    }
}

function Invoke-WithRetries {
    param(
        [string]$Activity,
        [ScriptBlock]$Action
    )
    $attempt = 0
    while ($true) {
        $attempt++
        try {
            & $Action
            return
        } catch {
            if ($attempt -ge $MaxAttempts) {
                throw "${Activity} failed after ${MaxAttempts} attempts: $($_.Exception.Message)"
            }
            $delay = $BaseDelaySec * [Math]::Pow(2, $attempt - 1)
            Write-Warning "${Activity} failed (attempt $attempt/$MaxAttempts): $($_.Exception.Message). Retrying in ${delay}s..."
            Start-Sleep -Seconds ([int]$delay)
        }
    }
}

function Ensure-Uv {
    Add-LocalToolPaths
    Sync-EnvironmentPath
    if (Test-Command "uv") {
        return
    }

    Write-Phase "Installing uv (Astral installer)"
    Invoke-WithRetries "Install uv" {
        Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1" -UseBasicParsing | Invoke-Expression
    }

    Add-LocalToolPaths
    Sync-EnvironmentPath

    if (-not (Test-Command "uv")) {
        throw "uv was installed but is not on PATH in this session. Close this window, open a new PowerShell window from the repo folder, run .\setup-windows.cmd again."
    }
}

function Get-NodeWindowsArchiveLabel {
    if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") {
        return "win-arm64"
    }
    return "win-x64"
}

function Test-NodeMeetsMinimum {
    if (-not ((Test-Command "node") -and (Test-Command "npm"))) {
        return $false
    }
    try {
        $nodeMajor = [int](& node -p "Number(process.versions.node.split('.')[0])")
    } catch {
        return $false
    }
    return $nodeMajor -ge $MinimumNodeMajor
}

function Get-WindowsSetupEnvironmentSummary {
    $summary = [ordered]@{
        OsCaption        = $null
        OsVersion        = $null
        OsBuild          = $null
        OsArchitecture     = $null
        ProcessorArchEnv = $env:PROCESSOR_ARCHITECTURE
    }
    try {
        $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
        $summary.OsCaption = $os.Caption
        $summary.OsVersion = $os.Version
        $summary.OsBuild = $os.BuildNumber
        $summary.OsArchitecture = $os.OSArchitecture
    } catch {
        $summary.OsCaption = "Could not query Win32_OperatingSystem: $($_.Exception.Message)"
    }
    return $summary
}

function Get-ResolvedNodePortableDownloadUrl {
    try {
        $res = Invoke-WebRequest -Uri "https://nodejs.org/dist/index.json" -UseBasicParsing -TimeoutSec 15
        $index = $res.Content | ConvertFrom-Json
        $lts = @($index | Where-Object { $_.lts } | Select-Object -First 1)
        if (-not $lts) {
            return $null
        }
        $label = Get-NodeWindowsArchiveLabel
        $verTag = $lts.version
        $zipName = "node-${verTag}-${label}.zip"
        return "https://nodejs.org/dist/${verTag}/${zipName}"
    } catch {
        return $null
    }
}

function Write-SetupAuditReport {
    Write-Phase "Environment audit (read-only)"
    Add-LocalToolPaths
    Sync-EnvironmentPath
    if (Test-Path (Join-Path $PortableNodeRoot "node.exe")) {
        $env:Path = "$(Resolve-Path $PortableNodeRoot).Path;$env:Path"
    }

    $os = Get-WindowsSetupEnvironmentSummary
    Write-Host "  Operating system : $($os.OsCaption)"
    if ($os.OsVersion) {
        Write-Host "  OS version       : $($os.OsVersion) (build $($os.OsBuild))"
    }
    if ($os.OsArchitecture) {
        Write-Host "  OS architecture  : $($os.OsArchitecture)"
    }
    Write-Host "  Processor (env)  : $($os.ProcessorArchEnv)  [used for Node portable zip selection: $(Get-NodeWindowsArchiveLabel)]"
    Write-Host "  PowerShell       : $($PSVersionTable.PSVersion) [$($PSVersionTable.PSEdition)]"
    Write-Host "  Repository       : $RootDir"

    $freeGiB = $null
    try {
        $driveName = (Resolve-Path $RootDir).Drive.Name
        $di = [System.IO.DriveInfo]::new("${driveName}:\")
        $freeGiB = [Math]::Round($di.AvailableFreeSpace / 1GB, 2)
        Write-Host "  Free space       : ~${freeGiB} GiB on drive ${driveName}: (minimum required this run: ${MinDiskGiB} GiB)"
    } catch {
        Write-Host "  Free space       : (could not read)"
    }

    Write-Host ""
    Write-Host "  Required commands (before install steps):" -ForegroundColor DarkCyan
    Write-Host "    git            : $(if (Test-Command 'git') { 'present (' + (& git --version 2>&1) + ')' } else { 'not on PATH (optional for running; needed to clone/update with git)' })"
    Write-Host "    winget         : $(if (Test-Command 'winget') { 'present' } else { 'not on PATH (Node can still be installed via Chocolatey or portable zip)' })"
    Write-Host "    choco          : $(if (Test-Command 'choco') { 'present' } else { 'not on PATH' })"
    Write-Host "    uv             : $(if (Test-Command 'uv') { 'present (' + (& uv --version 2>&1) + ')' } else { 'missing (will install)' })"

    if (-not (Test-Command "node")) {
        Write-Host "    node / npm     : missing on PATH" -ForegroundColor Yellow
    } elseif (-not (Test-Command "npm")) {
        Write-Host "    node / npm     : node found ($(& node --version 2>&1)), npm missing" -ForegroundColor Yellow
    } elseif (Test-NodeMeetsMinimum) {
        Write-Host "    node / npm     : ok (node $(& node --version 2>&1), npm $(& npm --version 2>&1))" -ForegroundColor Green
    } else {
        try {
            $maj = [int](& node -p "Number(process.versions.node.split('.')[0])" 2>&1)
        } catch {
            $maj = "?"
        }
        Write-Host "    node / npm     : below minimum $MinimumNodeMajor+ (resolved major: $maj, $(& node --version 2>&1)) — will upgrade/replace" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "  Python           : not required pre-installed — uv will provision Python ($PythonVersionPreferred preferred, then 3.12/3.13 fallbacks) and sync from uv.lock into .venv"
    Write-Host ""
    Write-Host "  Download / install sources this script uses:" -ForegroundColor DarkCyan
    Write-Host "    uv bootstrap   : https://astral.sh/uv/install.ps1"
    Write-Host "    Node LTS list  : https://nodejs.org/dist/index.json"
    $resolvedNode = Get-ResolvedNodePortableDownloadUrl
    if ($resolvedNode) {
        Write-Host "    Node portable  : $resolvedNode (used if winget/Chocolatey do not yield Node $MinimumNodeMajor+)"
    } else {
        Write-Host "    Node portable  : (could not resolve yet — check network; URL is built from index.json + $(Get-NodeWindowsArchiveLabel))"
    }
    Write-Host "    winget package : OpenJS.NodeJS.LTS (Microsoft winget catalog)"
    Write-Host "    Camoufox       : fetched via  uv run python -m camoufox fetch  after Python env exists"

    Write-Host ""
}

function Invoke-WingetNodeInstall {
    if (-not (Test-Command "winget")) {
        return
    }

    Write-Phase "Installing Node.js LTS via winget"
    try {
        $wingetArgs = @(
            "install", "--id", "OpenJS.NodeJS.LTS", "--exact",
            "--accept-package-agreements", "--accept-source-agreements"
        )
        & winget @wingetArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "winget exited with code $LASTEXITCODE (may be OK if Node is already installed or pending reboot)."
        }
    } catch {
        Write-Warning "winget Node install did not complete cleanly: $($_.Exception.Message)"
    }

    Sync-EnvironmentPath
    Add-LocalToolPaths
}

function Invoke-ChocolateyNodeInstall {
    if (-not (Test-Command "choco")) {
        return
    }

    Write-Phase "Installing Node.js LTS via Chocolatey (may require an elevated shell)"
    try {
        & choco install nodejs-lts -y --no-progress
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Chocolatey exited with code $LASTEXITCODE."
        }
    } catch {
        Write-Warning "Chocolatey Node install failed: $($_.Exception.Message)"
    }

    Sync-EnvironmentPath
    Add-LocalToolPaths
}

function Install-NodePortableZip {
    Write-Phase "Installing Node.js LTS as a portable per-user build (no winget required)"

    $label = Get-NodeWindowsArchiveLabel
    $index = Invoke-WithRetries "Fetch Node.js version index" {
        Invoke-RestMethod -Uri "https://nodejs.org/dist/index.json" -UseBasicParsing
    }

    $lts = @($index | Where-Object { $_.lts } | Select-Object -First 1)
    if (-not $lts) {
        throw "Could not read Node.js LTS metadata from nodejs.org/dist/index.json"
    }

    $verTag = $lts.version
    $zipName = "node-${verTag}-${label}.zip"
    $zipUrl = "https://nodejs.org/dist/${verTag}/${zipName}"
    $tmpZip = Join-Path $env:TEMP $zipName

    Invoke-WithRetries "Download $zipUrl" {
        Invoke-WebRequest -Uri $zipUrl -OutFile $tmpZip -UseBasicParsing
    }

    $stage = Join-Path $env:TEMP "node-portable-$verTag"
    if (Test-Path $stage) {
        Remove-Item -Recurse -Force $stage
    }
    Expand-Archive -Path $tmpZip -DestinationPath $stage -Force

    $inner = Get-ChildItem -Path $stage -Directory | Select-Object -First 1
    if (-not $inner) {
        throw "Unexpected Node archive layout under $stage"
    }

    if (Test-Path $PortableNodeRoot) {
        Remove-Item -Recurse -Force $PortableNodeRoot
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $PortableNodeRoot -Parent) | Out-Null
    Move-Item -Path $inner.FullName -Destination $PortableNodeRoot

    Remove-Item -Force $tmpZip -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $normRoot = (Resolve-Path $PortableNodeRoot).Path
    $parts = @($userPath -split ";" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    if ($parts -notcontains $normRoot) {
        $newUserPath = ($normRoot, $parts) -join ";"
        [Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
    }

    Add-LocalToolPaths
    Sync-EnvironmentPath
    $env:Path = "$normRoot;$env:Path"
}

function Prepend-PortableNodeOnPath {
    $exe = Join-Path $PortableNodeRoot "node.exe"
    if (-not (Test-Path $exe)) {
        return
    }
    $normRoot = (Resolve-Path $PortableNodeRoot).Path
    $env:Path = "$normRoot;$env:Path"
}

function Upgrade-NodeViaWinget {
    if (-not (Test-Command "winget")) {
        return
    }

    Write-Phase "Upgrading Node.js LTS via winget (only applies to winget-managed installs)"
    & winget upgrade --id OpenJS.NodeJS.LTS --exact --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "winget upgrade exited with code $LASTEXITCODE (typical when Node was never installed via winget)."
    }

    Sync-EnvironmentPath
    Add-LocalToolPaths
}

function Ensure-Node {
    Add-LocalToolPaths
    Sync-EnvironmentPath
    Prepend-PortableNodeOnPath

    if (Test-NodeMeetsMinimum) {
        return
    }

    if ((Test-Command "node") -and (Test-Command "npm")) {
        Write-Warning "Node.js on PATH is below $MinimumNodeMajor. Trying winget upgrade first."
        Upgrade-NodeViaWinget
        Prepend-PortableNodeOnPath
        if (Test-NodeMeetsMinimum) {
            return
        }
    }

    Invoke-WingetNodeInstall
    Prepend-PortableNodeOnPath
    if (Test-NodeMeetsMinimum) {
        return
    }

    Invoke-ChocolateyNodeInstall
    Prepend-PortableNodeOnPath
    if (Test-NodeMeetsMinimum) {
        return
    }

    Install-NodePortableZip
    Prepend-PortableNodeOnPath

    if (-not (Test-Command "node")) {
        throw "Node.js is still not available on PATH. Install Node.js ${MinimumNodeMajor}+ from https://nodejs.org/, restart the PC if prompted, then rerun setup."
    }
    if (-not (Test-Command "npm")) {
        throw "npm is not available next to node.exe. Reinstall Node.js LTS, then rerun setup."
    }

    if (-not (Test-NodeMeetsMinimum)) {
        throw @"
Node.js $MinimumNodeMajor+ is required, but this shell still resolves $(node --version).
Uninstall obsolete Node.js from Windows Settings -> Apps, or remove legacy Node folders from PATH, then rerun setup.
If setup installed a portable Node under $PortableNodeRoot, that copy is valid; an older install is taking precedence.
"@
    }
}

function Setup-Python {
    param([string]$PythonVer)

    Write-Phase "Syncing Python $PythonVer environment with uv.lock"
    Push-Location $RootDir
    try {
        Invoke-WithRetries "uv python install" {
            & uv python install $PythonVer
        }
        Invoke-WithRetries "uv sync" {
            & uv sync --extra dev --python $PythonVer
        }
    }
    finally {
        Pop-Location
    }
}

function Invoke-PythonSetupWithFallback {
    $dedupe = @{}
    $tryVersions = foreach ($v in @($PythonVersionPreferred, "3.12", "3.13")) {
        if (-not $dedupe.ContainsKey($v)) {
            $dedupe[$v] = $true
            $v
        }
    }

    $lastError = $null
    foreach ($ver in $tryVersions) {
        try {
            Setup-Python -PythonVer $ver
            return
        } catch {
            $lastError = $_
            Write-Warning "Python setup with $ver failed: $($_.Exception.Message)"
        }
    }
    throw "Could not create the Python virtual environment. Last error: $($lastError.Exception.Message)"
}

function Fetch-Browser {
    if ($SkipBrowser) {
        return
    }

    Add-LocalToolPaths
    Sync-EnvironmentPath
    Write-Phase "Downloading Camoufox browser payload (large; may take several minutes)"
    Push-Location $RootDir
    try {
        Invoke-WithRetries "camoufox fetch" {
            & uv run python -m camoufox fetch
        }
    }
    finally {
        Pop-Location
    }
}

function Setup-Gui {
    if ($SkipGui) {
        return
    }

    Ensure-Node
    Write-Phase "Installing Electron GUI dependencies from package-lock.json (npm ci; may take a few minutes)"
    Push-Location $GuiDir
    try {
        Invoke-WithRetries "npm ci" {
            & npm ci
        }
    }
    finally {
        Pop-Location
    }
}

Write-Phase "youtube-scrape Windows setup"
Write-Host "Repository: $RootDir"
Assert-RepositoryLayout

if (-not $SkipAudit) {
    Write-SetupAuditReport
}

if (-not $SkipPreflight) {
    Test-DiskSpace -MinGiB $MinDiskGiB
    Test-NetworkReachability
    if (-not (Test-Command "git")) {
        Write-Warning "Git is not on PATH. The project files you have are enough to run the app; install Git from https://git-scm.com/download/win only if you plan to pull updates."
    }
}

Ensure-Uv
Invoke-PythonSetupWithFallback
Fetch-Browser
Setup-Gui

Write-Phase "Setup complete"
Write-Host "Run the CLI: uv run youtube-scrape --help" -ForegroundColor Green
Write-Host "Run the GUI: .\start-gui.ps1   or   .\start-gui.cmd (recommended)" -ForegroundColor Green
if ($SkipBrowser) {
    Write-Warning "Camoufox was not downloaded (--SkipBrowser). Run: uv run python -m camoufox fetch"
}
if ($SkipGui) {
    Write-Warning "GUI dependencies were skipped (--SkipGui). Run setup again without -SkipGui when you need the Electron app."
}
