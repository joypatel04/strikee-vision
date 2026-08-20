@echo off
REM Strikee Vision - Windows bring-up wrapper.
REM Double-click this, or run it from a cmd prompt in the local-core directory.
REM Optional: pass the DVR RTSP URL so the doctor also proves stream decoding.
REM
REM   windows-setup.bat "rtsp://USER:PASS@192.168.0.108:554/cam/realmonitor?channel=1&subtype=0"
REM
REM Keep the URL in double quotes - it contains &.
REM If the password contains @, URL-encode it as %40.

cd /d "%~dp0.."

if "%~1"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "packaging\windows-setup.ps1"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "packaging\windows-setup.ps1" -Rtsp "%~1"
)

echo.
pause
