@echo off
setlocal
set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%scripts\start_workflow_env.ps1" -Environment prod -OpenBrowser
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
    echo [workflow-start] failed with exit code %EXIT_CODE%.
    if not defined WORKFLOW_NO_PAUSE_ON_FAIL pause
)
endlocal
exit /b %EXIT_CODE%
