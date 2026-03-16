@echo off
setlocal

if not exist venv\Scripts\activate (
  echo [ERROR] venv not found. Run scripts\install.bat first.
  exit /b 1
)

call venv\Scripts\activate

if "%1"=="--debug" (
  python app\main.py --debug
) else (
  python app\main.py
)

endlocal
