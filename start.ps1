# Linkareer AI Career Hub - Startup Script (PowerShell)
$ErrorActionPreference = "Stop"

# Fix working directory to the script's folder
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Linkareer AI Career Hub - Startup Script" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1. Check Python ───────────────────────────────────────────
$pythonCmd = $null
foreach ($cmd in @("python", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") {
            $pythonCmd = $cmd
            Write-Host "[OK] $ver detected." -ForegroundColor Green
            break
        }
    } catch { }
}

if (-not $pythonCmd) {
    Write-Host "[ERROR] Python 3 not found." -ForegroundColor Red
    Write-Host "        Install from: https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "        Make sure to check 'Add Python to PATH' during install." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# ── Step 2. Create virtual environment if missing ─────────────────
$venvActivate = ".venv\Scripts\Activate.ps1"
if (-not (Test-Path $venvActivate)) {
    Write-Host ""
    Write-Host "[SETUP] Creating virtual environment (.venv)..." -ForegroundColor Yellow
    & $pythonCmd -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "[OK] Virtual environment created." -ForegroundColor Green
}

# ── Step 3. Activate virtual environment ──────────────────────────
Write-Host "[OK] Activating virtual environment..." -ForegroundColor Green
& $venvActivate

# Use venv python directly to avoid PATH issues
$venvPython = ".venv\Scripts\python.exe"
$venvPip    = ".venv\Scripts\pip.exe"

# ── Step 4. Upgrade pip ────────────────────────────────────────────
& $venvPython -m pip install --upgrade pip --quiet

# ── Step 5. Install dependencies ──────────────────────────────────
if (Test-Path "requirements.txt") {
    Write-Host ""
    Write-Host "[SETUP] Installing packages from requirements.txt..." -ForegroundColor Yellow
    & $venvPip install -r requirements.txt --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Package installation failed." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "[OK] All packages installed." -ForegroundColor Green
} else {
    Write-Host "[WARN] requirements.txt not found. Skipping." -ForegroundColor Yellow
}

# ── Step 6. Warn if .env missing ──────────────────────────────────
if (-not (Test-Path ".env")) {
    Write-Host ""
    Write-Host "[WARN] .env file not found!" -ForegroundColor Yellow
    Write-Host "       Place your .env file in the project root." -ForegroundColor Yellow
    Start-Sleep -Seconds 3
}

# ── Step 7. Start server ───────────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Starting server at http://localhost:8000 ..." -ForegroundColor Cyan
Write-Host "  Press Ctrl+C to stop." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Open browser after 2 seconds (server needs time to start)
Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2
    Start-Process "chrome.exe" -ArgumentList "http://localhost:8000"
} | Out-Null

& $venvPython backend/main.py

Write-Host ""
Write-Host "[INFO] Server stopped." -ForegroundColor Gray
Read-Host "Press Enter to exit"
