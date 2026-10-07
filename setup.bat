@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
py -3 -m venv .venv
if not errorlevel 1 goto install
for %%V in (314 313 312 311 310) do (
    if exist "%LocalAppData%\Programs\Python\Python%%V\python.exe" (
        "%LocalAppData%\Programs\Python\Python%%V\python.exe" -m venv .venv
        if not errorlevel 1 goto install
    )
)
echo Install 64-bit Python 3.10 or newer from python.org, then run this again.
pause
exit /b 1
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" hand_tracker.py --download-model
if errorlevel 1 goto failed
echo Ready! Double-click run.bat to start your webcam.
pause
exit /b 0
:failed
echo Setup did not finish. Check the error above and your internet connection.
pause
exit /b 1
