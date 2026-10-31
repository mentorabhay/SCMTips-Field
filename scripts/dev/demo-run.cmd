@echo off
rem The 3-minute demo run on Windows - from a Command Prompt in <repo>:
rem   scripts\dev\demo-run.cmd <the SCMTIPS core checkout> [--po PO-26-1002] [--scenario magnet-export-curbs]
rem   (or set SCMTIPS_CORE_DIR first and double-click). See docs\DEMO_RUN.md for what it needs and each beat.
rem Same logic as demo-run.ps1 / tools/dev_stack/demo_run.py (the .sh file is for Linux/macOS).
setlocal
cd /d "%~dp0..\.."
set "PS=powershell"
where pwsh >nul 2>nul && set "PS=pwsh"
%PS% -NoProfile -ExecutionPolicy Bypass -File "%~dp0demo-run.ps1" %*
set rc=%ERRORLEVEL%
echo.
if not "%rc%"=="0" echo The demo run stopped at a beat - see the recovery line above and var\demo-run\*.log
pause
exit /b %rc%
