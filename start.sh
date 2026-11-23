#!/bin/bash
# Linkareer AI Career Hub - Startup Script for macOS/Linux (uv)

# Exit on error
set -e

# Change directory to the script's directory
cd "$(dirname "$0")"

echo -e "\033[0;36m============================================================\033[0m"
echo -e "\033[0;36m  Linkareer AI Career Hub - Startup Script (uv)\033[0m"
echo -e "\033[0;36m============================================================\033[0m"
echo ""

# ── Step 1. Check if uv is installed ───────────────────────────────
if ! command -v uv &> /dev/null; then
    echo -e "\033[0;31m[ERROR] 'uv' is not installed.\033[0m"
    echo -e "\033[0;33m        Installing 'uv' via curl...\033[0m"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Add to current path just in case
    export PATH="$HOME/.local/bin:$PATH"
    
    if ! command -v uv &> /dev/null; then
        echo -e "\033[0;31m[ERROR] Failed to install 'uv'. Please install it manually:\033[0m"
        echo -e "        https://github.com/astral-sh/uv"
        exit 1
    fi
    echo -e "\033[0;32m[OK] 'uv' installed successfully.\033[0m"
fi

# ── Step 2. Create virtual environment using uv ────────────────────
if [ ! -d ".venv" ]; then
    echo -e "\033[0;33m[SETUP] Creating virtual environment (.venv) using uv...\033[0m"
    uv venv
    echo -e "\033[0;32m[OK] Virtual environment created.\033[0m"
fi

# ── Step 3. Install/Sync dependencies ─────────────────────────────
if [ -f "requirements.txt" ]; then
    echo ""
    echo -e "\033[0;33m[SETUP] Syncing packages from requirements.txt with uv...\033[0m"
    uv pip install -r requirements.txt
    echo -e "\033[0;32m[OK] All packages installed.\033[0m"
else
    echo -e "\033[0;33m[WARN] requirements.txt not found. Skipping dependency installation.\033[0m"
fi

# ── Step 4. Warn if .env missing ──────────────────────────────────
if [ ! -f ".env" ]; then
    echo ""
    echo -e "\033[0;33m[WARN] .env file not found!\033[0m"
    echo -e "\033[0;33m       Place your .env file in the project root.\033[0m"
    sleep 3
fi

# ── Step 5. Free port 8000 if occupied ────────────────────────────
echo ""
echo -e "\033[0;33m[SETUP] Checking port 8000...\033[0m"
uv run backend/scripts/free_port.py 8000

# ── Step 6. Start server and open browser ─────────────────────────
echo ""
echo -e "\033[0;36m============================================================\033[0m"
echo -e "\033[0;36m  Starting server at http://localhost:8000 ...\033[0m"
echo -e "\033[0;36m  Press Ctrl+C to stop.\033[0m"
echo -e "\033[0;36m============================================================\033[0m"
echo ""

# Open browser after 2 seconds
(sleep 2 && open http://localhost:8000) &

# Run the application using uv run to ensure the venv is used
uv run backend/main.py

echo ""
echo -e "\033[0;90m[INFO] Server stopped.\033[0m"
