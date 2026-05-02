# Start the Electron + Vite dev GUI from the repository root on Windows.
$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PortableNode = Join-Path $env:LOCALAPPDATA "youtube-scrape-tools\nodejs-current"
if (Test-Path (Join-Path $PortableNode "node.exe")) {
    $env:Path = "$(Resolve-Path $PortableNode).Path;$env:Path"
}
$GuiDir = Join-Path $RootDir "gui"
$PythonExe = Join-Path $RootDir ".venv\Scripts\python.exe"

if (Test-Path $PythonExe) {
    $env:PYTHON_PATH = if ($env:PYTHON_PATH) { $env:PYTHON_PATH } else { $PythonExe }
}

$env:NO_SANDBOX = if ($env:NO_SANDBOX) { $env:NO_SANDBOX } else { "1" }

if (-not (Test-Path (Join-Path $GuiDir "node_modules"))) {
    Write-Host "First run: installing GUI dependencies in gui/ ..."
    Push-Location $GuiDir
    try {
        npm ci
    }
    finally {
        Pop-Location
    }
}

Push-Location $GuiDir
try {
    npm run dev
}
finally {
    Pop-Location
}
