@echo off
echo ============================================
echo   Gitter Start
echo   Starting PowerShell Script...
echo ============================================
echo.

REM Check PowerShell
powershell -Command "Get-Host" >nul 2>&1
if errorlevel 1 (
    echo [Error] PowerShell not found
    pause
    exit /b 1
)

REM Run PowerShell
powershell -ExecutionPolicy Bypass -File "%~dp0start.ps1"

if errorlevel 1 (
    echo.
    echo [Error] Start failed, check start.log
    pause
)
