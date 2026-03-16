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

pushd "%ROOT_DIR%"
if errorlevel 1 goto :error

set ARGS=%*
if "%ARGS%"=="" (
  set "ARGS=--gui"
  echo [INFO] Starting app with default GUI mode...
) else (
  echo [INFO] Starting app with args: %ARGS%
)

python -m app.main %ARGS%
set "EXIT_CODE=%errorlevel%"
popd
if not "%EXIT_CODE%"=="0" goto :error_with_code

echo.
echo [SUCCESS] App exited normally.
echo [INFO] Press any key to close this window.
pause >nul
exit /b 0

:error_with_code
echo.
echo [ERROR] App exited with code %EXIT_CODE%.
echo [ERROR] Keeping this window open so you can read the error.
pause
exit /b %EXIT_CODE%

:error
echo.
echo [ERROR] App launcher failed with code %errorlevel%.
echo [ERROR] Keeping this window open so you can read the error.
pause
exit /b %errorlevel%
