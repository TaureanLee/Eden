@echo off
REM Eden - double-click launcher for Windows.
REM Runs run.ps1 (which sets up the environment once, then starts Eden).
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
if errorlevel 1 pause
