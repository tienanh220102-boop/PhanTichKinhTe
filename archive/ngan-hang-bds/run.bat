@echo off
chcp 65001 >nul
echo ===================================================
echo  Banking ^& BDS Agent — Thi truong Phia Nam VN
echo ===================================================

REM Kiem tra GEMINI_API_KEY
if "%GEMINI_API_KEY%"=="" (
    echo [LOI] Chua set GEMINI_API_KEY
    echo.
    echo Cach set tam thoi:
    echo   set GEMINI_API_KEY=your_key_here
    echo.
    echo Cach set vinh vien: Control Panel > System > Environment Variables
    pause
    exit /b 1
)

cd /d "%~dp0"
python scripts\banking_realestate_agent.py
echo.
echo Bao cao HTML duoc luu trong thu muc: outputs\
pause
