@echo off
rem Earth2Road for Windows: double-click to play. The first run installs everything
rem (setup.ps1: Python packages, Godot, car models, offline example map); later runs
rem start the game right away (start.ps1). Arguments are passed on to start.ps1.
setlocal
cd /d "%~dp0"
title Earth2Road

rem Pinned packages have wheels for 64-bit CPython 3.11-3.14 only; setup.ps1 picks the same way.
set "PYCHECK=import sys, sysconfig; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 14) and sysconfig.get_platform() == 'win-amd64' else 1)"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "%PYCHECK%" >nul 2>nul && goto python_ok
)
for %%V in (3.14 3.13 3.12 3.11) do (
    py -%%V -c "%PYCHECK%" >nul 2>nul && goto python_ok
)
python -c "%PYCHECK%" >nul 2>nul && goto python_ok
goto no_python

:python_ok

if not exist ".venv\Scripts\python.exe" goto setup
if not exist ".venv\Scripts\earth2road.exe" goto setup
if not exist ".tools\Godot_v4.6-stable_win64.exe" goto setup
if not exist "game\.godot" goto setup
if not exist "game\data\active_map" goto setup
goto start

:setup
echo First run: installing Earth2Road. This downloads several hundred MB (about 1.2 GB on
echo disk) and takes a few minutes.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
    echo.
    echo Setup failed. Read the messages above, fix the problem and run Earth2Road.cmd again.
    pause
    exit /b 1
)

:start
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 (
    echo.
    echo Earth2Road stopped with an error. Logs: %~dp0logs
    pause
    exit /b 1
)
exit /b 0

:no_python
echo Earth2Road needs 64-bit Python 3.11-3.14 (3.14 is tested). Newer Python (3.15+)
echo and 32-bit or ARM builds are not supported by the map and traffic packages yet.
where winget >nul 2>nul
if errorlevel 1 goto python_manual
choice /C YN /M "Install Python 3.14 for your user account with winget now"
if errorlevel 2 goto python_manual
winget install --exact --id Python.Python.3.14 --scope user --accept-package-agreements --accept-source-agreements
echo.
echo Close this window and run Earth2Road.cmd again so Windows picks up the new Python.
pause
exit /b 0

:python_manual
echo Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo then run Earth2Road.cmd again.
pause
exit /b 1
