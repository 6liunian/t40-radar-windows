@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\start_native_tap_radar.ps1"
if errorlevel 1 pause
