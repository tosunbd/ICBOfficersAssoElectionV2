@echo off
rem RS - reads a folder of scanned ballots and writes the two result reports (PDF) into this folder.
setlocal
cd /d "%~dp0"
title ICB ballot folder scan (RS)

set "PY="
set "NEED=import cv2, numpy, PIL, pypdfium2"

rem 1. a Python that already has the packages: this folder, this project, the main project
call :try ".venv\Scripts\python.exe"
call :try "..\icbOfficerAssoAPI\.venv\Scripts\python.exe"
call :try "..\..\ICBOfficersAssoElection\icbOfficerAssoAPI\.venv\Scripts\python.exe"
if defined PY goto run

rem 2. the Python installed on this PC, if it has the packages
py -3 -c "%NEED%" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto run
python -c "%NEED%" >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto run

echo The Python packages for this program are not installed on this PC.
echo Double click "0. install.bat" in this folder once - it needs internet - then run rs.bat again.
goto end

:run
%PY% "%~dp0rs.py" %*

:end
echo.
pause
exit /b

:try
if defined PY exit /b
if not exist "%~1" exit /b
"%~1" -c "%NEED%" >nul 2>&1
if not errorlevel 1 set PY="%~f1"
exit /b
