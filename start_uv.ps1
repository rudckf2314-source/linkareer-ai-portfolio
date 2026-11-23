# Linkareer AI Career Hub - Startup Script for Windows (uv)
$ErrorActionPreference = "Stop"

# Fix working directory to the script's folder
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Linkareer AI Career Hub - Startup Script (uv)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1. Check if uv is installed ───────────────────────────────
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCmd) {
    Write-Host "[ERROR] 'uv' is not installed or not in PATH." -ForegroundColor Red
    Write-Host "        Installing 'uv' via PowerShell..." -ForegroundColor Yellow
    try {
        powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
        # Refresh PATH for current session
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    } catch {
        Write-Host "[ERROR] Failed to auto-install 'uv'. Please install it manually:" -ForegroundColor Red
        Write-Host "        https://github.com/astral-sh/uv" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}

if (-not $uvCmd) {
    Write-Host "[ERROR] 'uv' is still not found. Please restart terminal or add it to PATH." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[OK] 'uv' detected." -ForegroundColor Green

# ── Step 2. Create virtual environment using uv ────────────────────
if (-not (Test-Path ".venv")) {
    Write-Host ""
    Write-Host "[SETUP] Creating virtual environment (.venv) using uv..." -ForegroundColor Yellow
    uv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "[OK] Virtual environment created." -ForegroundColor Green
}

# ── Step 3. Install dependencies using uv ──────────────────────────
if (Test-Path "requirements.txt") {
    Write-Host ""
    Write-Host "[SETUP] Syncing packages from requirements.txt with uv..." -ForegroundColor Yellow
    uv pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Package installation failed." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "[OK] All packages installed." -ForegroundColor Green
} else {
    Write-Host "[WARN] requirements.txt not found. Skipping." -ForegroundColor Yellow
}

# ── Step 4. Warn if .env missing ──────────────────────────────────
if (-not (Test-Path ".env")) {
    Write-Host ""
    Write-Host "[WARN] .env file not found!" -ForegroundColor Yellow
    Write-Host "       Place your .env file in the project root." -ForegroundColor Yellow
    Start-Sleep -Seconds 3
}

# ── Step 5. Free port 8000 if occupied ────────────────────────────
Write-Host ""
Write-Host "[SETUP] Checking port 8000..." -ForegroundColor Yellow
uv run backend/scripts/free_port.py 8000

# ── Step 6. Start server and open browser ─────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Starting server at http://localhost:8000 ..." -ForegroundColor Cyan
Write-Host "  Press Ctrl+C to stop." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Open browser after 2 seconds
Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2
    Start-Process "http://localhost:8000"
} | Out-Null

uv run backend/main.py

Write-Host ""
Write-Host "[INFO] Server stopped." -ForegroundColor Gray
Read-Host "Press Enter to exit"
