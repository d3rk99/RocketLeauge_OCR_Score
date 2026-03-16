@echo off
setlocal

REM Runner for Rocket League OCR tracker
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "ROOT_DIR=%%~fI"

if not exist "%ROOT_DIR%\venv\Scripts\activate" (
  echo [ERROR] venv not found. Run scripts\install.bat first.
  pause
  exit /b 1
)

call "%ROOT_DIR%\venv\Scripts\activate"
if errorlevel 1 goto :error

set ARGS=%*
if "%ARGS%"=="" (
  echo [INFO] Starting app...
) else (
  echo [INFO] Starting app with args: %ARGS%
)

python "%ROOT_DIR%\app\main.py" %ARGS%
if errorlevel 1 goto :error

echo.
echo [SUCCESS] App exited normally.
echo [INFO] Press any key to close this window.
pause >nul
exit /b 0

:error
echo.
echo [ERROR] App exited with code %errorlevel%.
echo [ERROR] Keeping this window open so you can read the error.
pause
exit /b %errorlevel%
