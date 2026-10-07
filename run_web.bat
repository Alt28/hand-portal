@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Please run setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, websockets" >nul 2>&1
if errorlevel 1 (
    echo Installing web interface dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements-web.txt
    if errorlevel 1 (
        pause
        exit /b 1
    )
)
echo Open http://127.0.0.1:8000 in your browser. Press Ctrl+C here to stop.
".venv\Scripts\python.exe" web_app.py %*
if errorlevel 1 pause
