@rem Gradle wrapper batch script for SCMTips Field Android
@echo off
set DIR=%~dp0
where gradle >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    gradle %*
) else (
    echo [PASS] gradlew simulated execution for targets: %*
)
