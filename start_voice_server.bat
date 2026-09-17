@echo off
setlocal
cd /d "%~dp0"
title VoxHing Local Whisper Server

echo ========================================
echo VoxHing - Local Whisper Voice Server
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python was not found.
    echo Install Python 3.10 or newer, then reopen this file.
    pause
    exit /b 1
)

python -c "import faster_whisper, fastapi, uvicorn, sounddevice, numpy, ctranslate2" >nul 2>&1
if errorlevel 1 (
    echo Installing missing Python packages...
    echo.
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Package installation failed.
        pause
        exit /b 1
    )
)

echo.
echo Starting VoxHing...
echo First launch can take a while because the Whisper model may be downloaded.
echo.
python local_whisper_server.py

echo.
echo VoxHing stopped.
pause
