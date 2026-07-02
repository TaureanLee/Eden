# Eden — one-step launcher for Windows (PowerShell).
# Sets up a local Python environment the first time, then starts Eden and
# opens your browser. Re-running is fast; setup only happens once.
#
#   .\run.ps1                 # start Eden, pick your headset in the browser
#   .\run.ps1 --synthetic     # no hardware: explore with a simulated brain
#   .\run.ps1 --port 5001     # any server.py flag is passed straight through

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$sentinel   = Join-Path $PSScriptRoot ".venv\.eden-deps-installed"

function Find-Python {
    foreach ($candidate in @(@("py", "-3"), @("python", ""), @("python3", ""))) {
        $exe = $candidate[0]
        try {
            $null = & $exe $candidate[1] --version 2>$null
            if ($LASTEXITCODE -eq 0) {
                if ($candidate[1]) { return ,@($exe, $candidate[1]) } else { return ,@($exe) }
            }
        } catch { }
    }
    return $null
}

if (-not (Test-Path $venvPython)) {
    Write-Host "Setting up Eden for the first time..." -ForegroundColor Green
    $py = Find-Python
    if (-not $py) {
        Write-Host "Python 3.10+ was not found. Install it from https://www.python.org/downloads/ and re-run." -ForegroundColor Red
        Read-Host "Press Enter to exit"; exit 1
    }
    & $py[0] $py[1..($py.Count-1)] -m venv .venv
}

if (-not (Test-Path $sentinel)) {
    Write-Host "Installing dependencies (one time)..." -ForegroundColor Green
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Dependency install failed. See the messages above." -ForegroundColor Red
        Read-Host "Press Enter to exit"; exit 1
    }
    New-Item -ItemType File -Path $sentinel -Force | Out-Null
}

Write-Host "Starting Eden... your browser will open at http://127.0.0.1:5000" -ForegroundColor Green
& $venvPython server.py $args
