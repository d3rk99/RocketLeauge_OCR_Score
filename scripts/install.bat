@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Windows installer for Rocket League OCR tracker
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "ROOT_DIR=%%~fI"

set "PYTHON_CMD="

echo [INFO] Detecting Python runtime...
call :detect_python
if "%PYTHON_CMD%"=="" (
  echo [WARN] Python 3.11+ not detected. Attempting automatic install via winget...
  call :install_python_with_winget
  if errorlevel 1 goto :error

  echo [INFO] Re-checking Python runtime after installation...
  call :detect_python
  if "%PYTHON_CMD%"=="" goto :python_not_found
)

echo [INFO] Using Python command: %PYTHON_CMD%

if not exist "%ROOT_DIR%\venv" (
  echo [INFO] Creating virtual environment...
  %PYTHON_CMD% -m venv "%ROOT_DIR%\venv"
  if errorlevel 1 goto :error
) else (
  echo [INFO] Using existing virtual environment.
)

call "%ROOT_DIR%\venv\Scripts\activate"
if errorlevel 1 goto :error

echo [INFO] Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 goto :error

echo [INFO] Installing requirements...
pip install -r "%ROOT_DIR%\requirements.txt"
if errorlevel 1 goto :error

where tesseract >nul 2>nul
if %errorlevel% neq 0 (
  echo [INFO] Tesseract not found on PATH. If you want to use Tesseract OCR, install it and set TESSERACT_CMD in .env.
) else (
  echo [INFO] Tesseract executable detected.
)

echo [SUCCESS] Install complete.
exit /b 0

:detect_python
set "PYTHON_CMD="

py -3.11 -c "import sys;sys.exit(0 if sys.version_info[:2] >= (3,11) else 1)" >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py -3.11"
  goto :eof
)

py -3 -c "import sys;sys.exit(0 if sys.version_info[:2] >= (3,11) else 1)" >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py -3"
  goto :eof
)

py -c "import sys;sys.exit(0 if sys.version_info[:2] >= (3,11) else 1)" >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py"
  goto :eof
)

python -c "import sys;sys.exit(0 if sys.version_info[:2] >= (3,11) else 1)" >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=python"
  goto :eof
)

goto :eof

:install_python_with_winget
where winget >nul 2>nul
if errorlevel 1 (
  echo [ERROR] winget is not available on this machine.
  echo [ERROR] Install Python 3.11+ manually from https://www.python.org/downloads/windows/
  echo [ERROR] and enable "Add python.exe to PATH" during setup.
  exit /b 1
)

echo [INFO] Installing Python 3.11 via winget (this can take a few minutes)...
winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
  echo [ERROR] winget failed to install Python 3.11.
  exit /b 1
)

REM Refresh PATH in this session in case installer updated user/machine PATH.
set "PATH=%PATH%;%LocalAppData%\Programs\Python\Python311;%LocalAppData%\Programs\Python\Python311\Scripts"
exit /b 0

:python_not_found
echo.
echo [ERROR] No suitable Python runtime was found after automatic install attempt.
echo [ERROR] Tried: py -3.11, py -3, py, and python.
echo [ERROR] Verify installs with: py -0p
pause
exit /b 103

:error
echo.
echo [ERROR] Install failed with exit code %errorlevel%.
echo [ERROR] Review the message above for details.
pause
exit /b %errorlevel%
