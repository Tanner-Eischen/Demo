@echo off
echo Setting up Chatterbox TTS Server...

REM Check if venv exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Starting Chatterbox TTS Server on http://localhost:8004
echo API docs: http://localhost:8004/docs
echo.
python server.py
