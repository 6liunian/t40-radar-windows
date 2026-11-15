@echo off
setlocal
set "PYTHON_EXE=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Missing project Python environment: %PYTHON_EXE%
  pause
  exit /b 1
)
start "T40 Web Radar" /min "%PYTHON_EXE%" "%~dp0server.py" --port 8768
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8768/"
