@echo off
rem ONE CLICK: double-click once on the PC (laptop) that will run the election
rem system.  It needs the internet this one time and does everything:
rem   - finds or installs Python and Node.js (nothing else on the PC is changed)
rem   - builds the Python environment for THIS PC and installs all packages
rem   - creates the settings file (.env) with a login secret of its own
rem   - installs the UI packages and builds the UI
rem   - opens the firewall for the other PCs on the intranet (ports 3000, 8000, 80)
rem   - laptop: no sleep on mains power, closing the lid does nothing
rem   - IIS on port 80 as an extra address, when IIS is available
rem Safe to run again (finished steps are skipped).  Then use "1. Start.bat":
rem it shows the addresses, e.g.
rem     http://localhost:3000/election/admin          (on this PC)
rem     http://<this-pc-ip>:3000/election/admin       (from the other PCs)
setlocal

rem ------------------------------------------------- settings you may change
rem Python version the API needs; an installed 64-bit copy of it is used if
rem one is found, otherwise it is installed into PYTHON_INSTALL_DIR (other
rem Python versions on the PC are not touched).
set "PYTHON_VERSION=3.14"
set "PYTHON_INSTALL_DIR=C:\Python\Python314"
rem Oldest Node.js accepted; older or missing -> a private copy in tools\node.
set "NODE_MIN_VERSION=20.9.0"
rem IIS site and URL prefix the system is published under (port 80).
set "IIS_SITE=Default Web Site"
set "IIS_APP_PATH=/election"
rem yes = do not set up IIS (the system is then used on port 3000 only, without
rem the /election prefix).  IIS is an extra: if it cannot be set up the
rem installation still succeeds.
set "SKIP_IIS=no"
rem yes = always delete and rebuild icbOfficerAssoAPI\.venv.  A .venv copied
rem from another PC is rebuilt automatically anyway.
set "RECREATE_VENV=no"
rem yes = leave the sleep / lid settings of this PC as they are.
set "SKIP_POWER_SETTINGS=no"
rem ---------------------------------------------------------------------------

title ICB Election System - Install
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
  echo Asking for administrator rights...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

set "EXTRA="
if /i "%SKIP_IIS%"=="yes" set "EXTRA=%EXTRA% -SkipIis"
if /i "%RECREATE_VENV%"=="yes" set "EXTRA=%EXTRA% -RecreateVenv"
if /i "%SKIP_POWER_SETTINGS%"=="yes" set "EXTRA=%EXTRA% -SkipPowerSettings"

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\install.ps1" -PythonVersion "%PYTHON_VERSION%" -PythonInstallDir "%PYTHON_INSTALL_DIR%" -NodeMinVersion "%NODE_MIN_VERSION%" -IisSite "%IIS_SITE%" -IisAppPath "%IIS_APP_PATH%" %EXTRA%
if errorlevel 1 (
  echo.
  echo INSTALLATION FAILED - see the message above, fix it and run "0. install.bat" again.
)
echo.
pause
