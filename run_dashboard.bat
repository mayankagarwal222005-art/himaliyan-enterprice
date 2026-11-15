@echo off
title PlateTrack AI - Vehicle ANPR & Stay Monitoring Dashboard
echo ======================================================================
echo           PlateTrack AI - Smart Vehicle ANPR Dashboard
echo ======================================================================
echo.
echo Starting Web Server on http://localhost:8000 ...
echo Real-time Indian Standard Time (IST) Active
echo.
cd /d "%~dp0"

if exist "C:\pt_env\Scripts\uvicorn.exe" (
    C:\pt_env\Scripts\uvicorn.exe server:app --host 127.0.0.1 --port 8000
) else if exist "venv\Scripts\uvicorn.exe" (
    venv\Scripts\uvicorn.exe server:app --host 127.0.0.1 --port 8000
) else (
    python -m uvicorn server:app --host 127.0.0.1 --port 8000
)
pause
