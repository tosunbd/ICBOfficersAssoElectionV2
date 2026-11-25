@echo off
rem Double-click to stop the ICB Election System (watchdog, API and UI).
rem Everything saved stays in the database; "1. Start.bat" brings it back.
title ICB Election System - Stop
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\stop-local.ps1"
echo.
pause
