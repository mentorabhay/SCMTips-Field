@echo off
rem Field-test stack on Windows - double-click, or run from a Command Prompt:
rem   run-field-stack.cmd              start everything, smoke test, new delivery, pairing QR
rem   run-field-stack.cmd up|down|status|smoke|delivery|pair
rem Same logic as run-field-stack.ps1 / tools/dev_stack/stack.py (the .sh file is for Linux/macOS).
setlocal
cd /d "%~dp0..\.."
set "PS1=%~dp0run-field-stack.ps1"
if "%~1"=="" goto all
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set rc=%ERRORLEVEL%
goto end

:all
echo ==== start the stack ====
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" up
set rc=%ERRORLEVEL%
if not "%rc%"=="0" goto failed
echo.
echo ==== smoke test: the phone journey without a phone ====
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" smoke
echo.
echo ==== a fresh inbound delivery to receive ====
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" delivery
echo.
echo ==== pairing QR for the phone (also saved as var\pairing-qr.svg) ====
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" pair
set rc=%ERRORLEVEL%
goto end

:failed
echo The stack did not start - see the messages above and var\log\*.log

:end
echo.
pause
exit /b %rc%
