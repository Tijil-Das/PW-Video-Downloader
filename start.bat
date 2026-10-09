@echo off
REM PW Downloader: single entry point. Ensures deps, then starts frontend + backend.
cd /d "%~dp0"
if not exist desktop\backend\install.py (
  echo install.py missing — cannot start.
  pause
  exit /b 1
)
python desktop\backend\install.py
if errorlevel 1 (
  echo Dependency install failed — fix the errors above.
  pause
  exit /b 1
)
start "PW Frontend" powershell -ExecutionPolicy Bypass -NoExit -Command "cd '%~dp0desktop\frontend'; npx vite --port 5173"
timeout /t 8 /nobreak >nul
set PW_DEV_URL=http://localhost:5173/
python "%~dp0desktop\backend\main.py"
pause
