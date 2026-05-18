@echo off
cd /d "%~dp0.."

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd_HHmmss'"') do set TS=%%i

git add -A

git diff --cached --quiet
if %errorlevel% equ 0 (
    echo [BACKUP] No changes to commit
    goto push
)

if "%~1"=="" (
    git commit -m "backup: %TS%"
) else (
    git commit -m "%~1"
)

:push
git push origin master
if %errorlevel% neq 0 (
    echo [BACKUP] Push failed
    exit /b 1
)

echo [BACKUP] Pushed to remote successfully
exit /b 0
