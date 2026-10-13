@echo off
rem Double-click launcher for Windows. Same as amanuense.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0amanuense.ps1" %*
pause
