@echo off
setlocal EnableExtensions

REM Windows installer for Rocket League OCR tracker

set "PYTHON_CMD="

if not exist venv (
  echo [INFO] Creating virtual environment...

  REM Try preferred launcher/runtime first.
  py -3.11 -m venv venv >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=py -3.11"

  REM Fallbacks for systems without exact 3.11 alias.
  if "%PYTHON_CMD%"=="" (
    py -3 -m venv venv >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3"
  )

  if "%PYTHON_CMD%"=="" (
    py -m venv venv >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py"
  )

  REM Final fallback: plain python on PATH.
  if "%PYTHON_CMD%"=="" (
    python -m venv venv >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
  )

  if "%PYTHON_CMD%"=="" goto :python_not_found

  echo [INFO] Virtual environment created using: %PYTHON_CMD%
) else (
  echo [INFO] Using existing virtual environment.
)

call venv\Scripts\activate
if errorlevel 1 goto :error

echo [INFO] Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 goto :error

echo [INFO] Installing requirements...
pip install -r requirements.txt
if errorlevel 1 goto :error

where tesseract >nul 2>nul
if %errorlevel% neq 0 (
  echo [INFO] Tesseract not found on PATH. If you want to use Tesseract OCR, install it and set TESSERACT_CMD in .env.
) else (
  echo [INFO] Tesseract executable detected.
)

echo [SUCCESS] Install complete.
exit /b 0

:python_not_found
echo.
echo [ERROR] No suitable Python runtime was found.
echo [ERROR] Tried: py -3.11, py -3, py, and python.
echo [ERROR] Install Python 3.11+ from https://www.python.org/downloads/windows/
echo [ERROR] and enable "Add python.exe to PATH" during setup.
echo [ERROR] You can verify installs with: py -0p
pause
exit /b 103

:error
echo.
echo [ERROR] Install failed with exit code %errorlevel%.
echo [ERROR] Review the message above for details.
pause
exit /b %errorlevel%
