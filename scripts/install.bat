@echo off
setlocal

REM Windows installer for Rocket League OCR tracker

if not exist venv (
  echo [INFO] Creating virtual environment...
  py -3.11 -m venv venv
  if errorlevel 1 goto :error
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

:error
echo.
echo [ERROR] Install failed with exit code %errorlevel%.
echo [ERROR] Review the message above for details.
pause
exit /b %errorlevel%
