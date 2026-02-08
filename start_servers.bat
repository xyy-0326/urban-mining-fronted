@echo off
setlocal

echo ============================================
echo   Urban Mining Map - Start Servers
echo ============================================
echo.

REM --- project paths (adjust if needed) ---
set BASE_DIR=E:\Kassel\WS2526\04urban_mining_data
set FRONT_DIR=%BASE_DIR%\frontend
set BACK_DIR=%BASE_DIR%\backend

set FRONT_PORT=5500
set BACK_PORT=8000

REM --- check folders ---
if not exist "%FRONT_DIR%" (
    echo [ERROR] Frontend folder not found: %FRONT_DIR%
    pause
    exit /b
)
if not exist "%BACK_DIR%\main.py" (
    echo [ERROR] Backend main.py not found: %BACK_DIR%\main.py
    pause
    exit /b
)

echo [1/2] Starting frontend server on port %FRONT_PORT% ...
cd /d %FRONT_DIR%
start /B python -m http.server %FRONT_PORT%

echo [2/2] Starting backend (FastAPI) on port %BACK_PORT% ...
cd /d %BACK_DIR%
start /B python -m uvicorn main:app --reload --port %BACK_PORT%

echo.
echo Frontend: http://127.0.0.1:%FRONT_PORT%/index.html
echo Backend:  http://127.0.0.1:%BACK_PORT%/ping
echo.

echo Opening browser for frontend...
start "" http://127.0.0.1:%FRONT_PORT%/index.html

echo ============================================
echo Keep this window open to keep servers running.
echo Close this window to stop both servers.
echo ============================================
echo.
pause

endlocal
