@echo off
setlocal
cd /d "%~dp0"
if exist "%USERPROFILE%\anaconda3\python.exe" (
    set "PATH=%USERPROFILE%\anaconda3\Library\bin;%USERPROFILE%\anaconda3\DLLs;%USERPROFILE%\anaconda3\Scripts;%USERPROFILE%\anaconda3;%PATH%"
)
if not exist ".venv\Scripts\python.exe" goto not_installed
set "SWIMCAST_PYTHON=.venv\Scripts\python.exe"
"%SWIMCAST_PYTHON%" -c "import ssl, requests, feedparser, tkinter; print(ssl.OPENSSL_VERSION)"
if errorlevel 1 goto failed
if "%~1"=="--check" exit /b 0
"%SWIMCAST_PYTHON%" swimcast_manager.py
if errorlevel 1 goto failed
exit /b 0
:not_installed
echo SwimCast is not set up yet. Double-click install_swimcast.bat first.
pause
exit /b 1
:failed
echo SwimCast could not start. Check the Python environment above.
pause
exit /b 1

