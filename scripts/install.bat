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

call :install_cuda_torch_if_possible

call :print_torch_diagnostics

where tesseract >nul 2>nul
if %errorlevel% neq 0 (
  echo [INFO] Tesseract not found on PATH. If you want to use Tesseract OCR, install it and set TESSERACT_CMD in .env.
) else (
  echo [INFO] Tesseract executable detected.
)

echo.
echo [SUCCESS] Install complete.
echo [INFO] Press any key to close this window.
pause >nul
exit /b 0

:install_cuda_torch_if_possible
where nvidia-smi >nul 2>nul
if errorlevel 1 (
  echo [INFO] NVIDIA GPU tooling not detected ^(nvidia-smi not found^). Keeping default Torch package.
  exit /b 0
)

echo [INFO] NVIDIA GPU detected. Attempting CUDA-enabled PyTorch install...

echo [INFO] Attempt 1: cu121 wheels (force reinstall)...
pip install --upgrade --force-reinstall --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu121
call :check_cuda_active
if not errorlevel 1 (
  echo [INFO] CUDA torch install validated using cu121.
  exit /b 0
)

echo [WARN] cu121 install did not produce CUDA-active torch.
echo [INFO] Attempt 2: cu124 wheels (force reinstall)...
pip install --upgrade --force-reinstall --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu124
call :check_cuda_active
if not errorlevel 1 (
  echo [INFO] CUDA torch install validated using cu124.
  exit /b 0
)

echo [WARN] CUDA-enabled PyTorch install attempts did not result in CUDA-active torch.
echo [WARN] Keeping currently installed torch package.
echo [WARN] Common causes: unsupported Python version for CUDA wheels, incompatible NVIDIA driver, or environment conflicts.
echo [WARN] Suggested checks:
echo        1) python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
echo        2) nvidia-smi
exit /b 0

:check_cuda_active
python -c "import torch,sys; sys.exit(0 if (torch.cuda.is_available() and torch.version.cuda is not None) else 1)" >nul 2>nul
exit /b %errorlevel%

:print_torch_diagnostics
python -c "import torch; print('[INFO] torch.__version__ =', torch.__version__); print('[INFO] torch.version.cuda =', torch.version.cuda); print('[INFO] torch.cuda.is_available =', torch.cuda.is_available()); print('[INFO] torch.cuda.device_count =', torch.cuda.device_count())" >nul 2>nul
if errorlevel 1 (
  echo [INFO] Torch not importable yet for CUDA check.
  exit /b 0
)

python -c "import torch; print('[INFO] torch.__version__ =', torch.__version__); print('[INFO] torch.version.cuda =', torch.version.cuda); print('[INFO] torch.cuda.is_available =', torch.cuda.is_available()); print('[INFO] torch.cuda.device_count =', torch.cuda.device_count())"

python -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)"
if not errorlevel 1 (
  echo [INFO] CUDA is active. EasyOCR can use GPU.
  exit /b 0
)

where nvidia-smi >nul 2>nul
if errorlevel 1 (
  echo [INFO] CPU-only mode expected on this machine.
) else (
  echo [WARN] NVIDIA GPU detected but Torch is still CPU-only.
  echo [WARN] Check Python version/wheel support and NVIDIA driver/CUDA compatibility.
)
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
