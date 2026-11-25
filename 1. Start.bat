@echo off
rem Double-click to start the ICB Election System.
rem This window then shows the addresses - on this PC (localhost) and for the
rem other PCs on the intranet (this PC's IP address) - and stays open as the
rem WATCHDOG: it restarts a server that stops and keeps the laptop awake.
rem Keep it open during the election; stop the system with "2. Stop.bat".
title ICB Election System - Start
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start-local.ps1" -Production
echo.
pause
