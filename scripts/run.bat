@echo off
setlocal

REM Runner for Rocket League OCR tracker

if not exist venv\Scripts\activate (
  echo [ERROR] venv not found. Run scripts\install.bat first.
  pause
  exit /b 1
)

call venv\Scripts\activate
if errorlevel 1 goto :error

set ARGS=%*
if "%ARGS%"=="" (
  echo [INFO] Starting app...
) else (
  echo [INFO] Starting app with args: %ARGS%
)

python app\main.py %ARGS%
if errorlevel 1 goto :error

exit /b 0

:error
echo.
echo [ERROR] App exited with code %errorlevel%.
echo [ERROR] Keeping this window open so you can read the error.
pause
exit /b %errorlevel%
