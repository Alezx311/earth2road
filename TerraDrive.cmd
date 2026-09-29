@echo off
rem TerraDrive for Windows: double-click to play. The first run installs everything
rem (setup.ps1: Python packages, Godot, car models, offline example map); later runs
rem start the game right away (start.ps1). Arguments are passed on to start.ps1.
setlocal
cd /d "%~dp0"
title TerraDrive

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto no_python

if not exist ".venv\Scripts\python.exe" goto setup
if not exist ".tools\Godot_v4.6-stable_win64.exe" goto setup
if not exist "game\.godot" goto setup
if not exist "game\data\active_map" goto setup
goto start

:setup
echo First run: installing TerraDrive. This downloads several hundred MB (about 1.2 GB on
echo disk) and takes a few minutes.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
    echo.
    echo Setup failed. Read the messages above, fix the problem and run TerraDrive.cmd again.
    pause
    exit /b 1
)

:start
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 (
    echo.
    echo TerraDrive stopped with an error. Logs: %~dp0logs
    pause
    exit /b 1
)
exit /b 0

:no_python
echo TerraDrive needs Python 3.11 or newer (3.14 is tested).
where winget >nul 2>nul
if errorlevel 1 goto python_manual
choice /C YN /M "Install Python 3.14 for your user account with winget now"
if errorlevel 2 goto python_manual
winget install --exact --id Python.Python.3.14 --scope user --accept-package-agreements --accept-source-agreements
echo.
echo Close this window and run TerraDrive.cmd again so Windows picks up the new Python.
pause
exit /b 0

:python_manual
echo Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo then run TerraDrive.cmd again.
pause
exit /b 1
