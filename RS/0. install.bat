@echo off
rem RS - one-time setup: makes the Python environment rs.bat uses (.venv in this folder)
rem and installs the packages of requirements.txt.  Needs internet.  Safe to run again.
setlocal
cd /d "%~dp0"
title ICB ballot folder scan (RS) - install

set "NEED=import cv2, numpy, PIL, pypdfium2"
set "VENV=.venv\Scripts\python.exe"

echo ICB ballot folder scan (RS) - install
echo ============================================================

rem ---- 1. already installed?
if not exist "%VENV%" goto findpython
"%VENV%" -c "%NEED%" >nul 2>&1
if not errorlevel 1 goto ready
"%VENV%" -c "import sys" >nul 2>&1
if not errorlevel 1 goto packages
echo The .venv folder here was made on another PC or for a removed Python: making it again ...
rmdir /s /q .venv

rem ---- 2. find Python on this PC: 64-bit, 3.10 or newer, and not the "free-threaded"
rem      build (python3.14t), for which the packages do not exist ready-made
:findpython
set "BASE="
set "GOOD=import sys, sysconfig; sys.exit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 and not sysconfig.get_config_var('Py_GIL_DISABLED') else 1)"
call :pick py -3.14
call :pick py -3.13
call :pick py -3.12
call :pick py -3.11
call :pick py -3.10
call :pick python
call :pick py -3
if defined BASE goto makevenv

echo Python was not found on this PC: installing Python 3.12 with winget ...
winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements
set "NEWPY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%NEWPY%" set BASE="%NEWPY%"
if defined BASE goto makevenv
echo.
echo Python could not be installed automatically.
echo Install Python 3.12 or newer from https://www.python.org/downloads/ - tick "Add python.exe to PATH" -
echo and run this file again.
goto failed

rem ---- 3. the environment of this folder
:makevenv
echo Making the Python environment in %~dp0.venv ...
%BASE% -m venv .venv
if not exist "%VENV%" echo The environment could not be made.
if not exist "%VENV%" goto failed

rem ---- 4. the packages
:packages
echo Installing the packages - this takes a minute or two ...
"%VENV%" -m pip install --disable-pip-version-check -r requirements.txt
"%VENV%" -c "%NEED%" >nul 2>&1
if errorlevel 1 echo.
if errorlevel 1 echo The packages could not be installed. Check the internet connection and run this file again.
if errorlevel 1 goto failed

:ready
echo.
"%VENV%" -c "import sys, cv2, numpy, PIL, pypdfium2; print('Python', sys.version.split()[0], '- OpenCV', cv2.__version__, '- NumPy', numpy.__version__, '- Pillow', PIL.__version__)"

rem ---- 5. the PDFs are printed by Microsoft Edge (part of Windows) or Chrome
set "BROWSER="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=Microsoft Edge"
if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=Microsoft Edge"
if not defined BROWSER if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER=Google Chrome"
if not defined BROWSER if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "BROWSER=Google Chrome"
if not defined BROWSER if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "BROWSER=Google Chrome"
if defined BROWSER echo PDF printing: %BROWSER%
if not defined BROWSER echo WARNING: Microsoft Edge / Chrome not found - the reports will be saved as HTML, not PDF.
if not exist "candidates.csv" echo WARNING: candidates.csv is missing in this folder.

echo.
echo READY. Double click rs.bat to scan a folder of ballots.
goto end

:failed
echo.
echo INSTALL NOT FINISHED.

:end
echo.
pause
exit /b

:pick
if defined BASE exit /b
%* -c "%GOOD%" >nul 2>&1
if not errorlevel 1 set "BASE=%*"
exit /b
