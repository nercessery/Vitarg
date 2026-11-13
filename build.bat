@echo off
REM Double-click to build. Works with any installed Python (e.g. 3.12+); falls back to a private Python automatically. Needs internet. Output: dist\Vitarg-Setup.exe
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build.ps1"
if errorlevel 1 (echo. & echo BUILD FAILED - see messages above. & pause & exit /b 1)
echo. & echo Build finished. & pause
