@echo off
echo Setting up Vision MCP Bridge Server...

REM Check if node_modules exists
if not exist "node_modules" (
    echo Installing dependencies...
    call npm install
)

echo.
echo Starting Vision MCP Bridge Server on http://localhost:8005
echo Make sure Z_AI_API_KEY is set in your environment
echo.

REM Set API key from parent .env if not already set
for /f "tokens=1,2 delims==" %%a in (..\..env) do (
    if "%%a"=="ZAI_API_KEY" set Z_AI_API_KEY=%%b
)

set Z_AI_API_KEY=%Z_AI_API_KEY% node server.js
