# Bootstrap a local development/runtime environment on Windows.
[CmdletBinding()]
param(
    [switch]$SkipGui,
    [switch]$SkipBrowser
)

$ErrorActionPreference = "Stop"
$PythonVersion = if ($env:PYTHON_VERSION) { $env:PYTHON_VERSION } else { "3.13" }
$MinimumNodeMajor = 18
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$GuiDir = Join-Path $RootDir "gui"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Add-LocalToolPaths {
    $paths = @(
        (Join-Path $env:USERPROFILE ".local\bin"),
        (Join-Path $env:USERPROFILE ".cargo\bin"),
        "C:\Program Files\nodejs"
    )

    foreach ($path in $paths) {
        if ((Test-Path $path) -and (($env:Path -split ";") -notcontains $path)) {
            $env:Path = "$path;$env:Path"
        }
    }
}

function Test-Command {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Ensure-Uv {
    Add-LocalToolPaths
    if (Test-Command "uv") {
        return
    }

    Write-Step "Installing uv"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    Add-LocalToolPaths

    if (-not (Test-Command "uv")) {
        throw "uv installed, but it is not on PATH. Open a new PowerShell window and rerun setup.ps1."
    }
}

function Install-NodeIfPossible {
    if (-not (Test-Command "winget")) {
        throw "Node.js $MinimumNodeMajor+ and npm are required. Install Node.js LTS or install winget, then rerun setup.ps1."
    }

    Write-Step "Installing Node.js LTS with winget"
    winget install --id OpenJS.NodeJS.LTS --exact --accept-package-agreements --accept-source-agreements
    Add-LocalToolPaths
}

function Ensure-Node {
    Add-LocalToolPaths
    if ((-not (Test-Command "node")) -or (-not (Test-Command "npm"))) {
        Install-NodeIfPossible
    }

    if (-not (Test-Command "node")) {
        throw "Node.js was not found after install."
    }

    if (-not (Test-Command "npm")) {
        throw "npm was not found after install."
    }

    $nodeMajor = [int](& node -p "Number(process.versions.node.split('.')[0])")
    if ($nodeMajor -lt $MinimumNodeMajor) {
        throw "Node.js $MinimumNodeMajor+ is required; found $(& node --version). Install a newer Node.js and rerun setup.ps1."
    }
}

function Setup-Python {
    Write-Step "Syncing Python environment with uv.lock"
    Push-Location $RootDir
    try {
        uv python install $PythonVersion
        uv sync --extra dev --python $PythonVersion
    }
    finally {
        Pop-Location
    }
}

function Fetch-Browser {
    if ($SkipBrowser) {
        return
    }

    Write-Step "Downloading Camoufox browser payload"
    Push-Location $RootDir
    try {
        uv run python -m camoufox fetch
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
    Write-Step "Installing Electron GUI dependencies from package-lock.json"
    Push-Location $GuiDir
    try {
        npm ci
    }
    finally {
        Pop-Location
    }
}

Ensure-Uv
Setup-Python
Fetch-Browser
Setup-Gui

Write-Step "Setup complete"
Write-Host "Run the CLI: uv run youtube-scrape --help"
Write-Host "Run the GUI: .\start-gui.ps1"
