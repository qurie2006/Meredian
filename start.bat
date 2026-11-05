@echo off
setlocal
cd /d "%~dp0"

echo ============================================================================
echo   MEREDIAN - Follow-the-Sun Engineering Memory (Windows Launcher)
echo ============================================================================

if not exist ".env" (
    if exist ".env.example" (
        echo [Meredian] Creating default .env from .env.example...
        copy /Y ".env.example" ".env" >nul
    )
)

set PYTHONPATH=.
set MEREDIAN_HOST=127.0.0.1
set MEREDIAN_PORT=8000

echo [Meredian] Starting Local Hindsight Server on http://127.0.0.1:8888 ...
start "Meredian Hindsight Server (8888)" /min cmd /c "set PYTHONPATH=. && python scripts/hindsight_local_server.py"

echo [Meredian] Opening http://%MEREDIAN_HOST%:%MEREDIAN_PORT% in your default browser...
start "" "http://%MEREDIAN_HOST%:%MEREDIAN_PORT%"

echo [Meredian] Starting Meredian API + Web Dashboard on http://%MEREDIAN_HOST%:%MEREDIAN_PORT% ...
echo (Press Ctrl+C to stop)
echo.
python -m uvicorn api.main:app --host %MEREDIAN_HOST% --port %MEREDIAN_PORT% --reload

