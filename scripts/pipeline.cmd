@echo off
REM Quick launcher for vo-demo-generator pipeline
REM Usage: pipeline.cmd <project_id>
REM Example: pipeline.cmd proj_7233fe2f

if "%~1"=="" (
    echo Usage: pipeline.cmd ^<project_id^>
    echo Example: pipeline.cmd proj_7233fe2f
    exit /b 1
)

powershell -ExecutionPolicy Bypass -File "%~dp0run-pipeline.ps1" -ProjectId %~1
