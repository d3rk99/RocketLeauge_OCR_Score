@echo off
setlocal

if not exist venv (
  py -3.11 -m venv venv
)

call venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

where tesseract >nul 2>nul
if %errorlevel% neq 0 (
  echo [INFO] Tesseract not found on PATH. If you want to use Tesseract OCR, install it and set TESSERACT_CMD in .env.
) else (
  echo [INFO] Tesseract executable detected.
)

echo Install complete.
endlocal
