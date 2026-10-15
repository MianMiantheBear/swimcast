@echo off
setlocal
cd /d "%~dp0"

if exist "%USERPROFILE%\anaconda3\python.exe" (
    set "PATH=%USERPROFILE%\anaconda3\Library\bin;%USERPROFILE%\anaconda3\DLLs;%USERPROFILE%\anaconda3\Scripts;%USERPROFILE%\anaconda3;%PATH%"
    set "SWIMCAST_BASE_PYTHON=%USERPROFILE%\anaconda3\python.exe"
) else (
    where python >nul 2>&1
    if errorlevel 1 goto no_python
    set "SWIMCAST_BASE_PYTHON=python"
)

"%SWIMCAST_BASE_PYTHON%" -c "import ssl, tkinter, sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
if errorlevel 1 goto bad_python
if "%~1"=="--check" exit /b 0

if not exist ".venv\Scripts\python.exe" (
    "%SWIMCAST_BASE_PYTHON%" -m venv ".venv"
    if errorlevel 1 goto venv_failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto install_failed

if exist "ffmpeg.exe" goto ready
where ffmpeg >nul 2>&1
if not errorlevel 1 goto ready
echo.
echo Python packages are installed, but FFmpeg is still needed.
echo Download a Windows build via https://ffmpeg.org/download.html
echo Then copy ffmpeg.exe from its bin folder beside this installer.
pause
exit /b 0

:ready
echo.
echo Setup is complete. Double-click start_swimcast.bat to open SwimCast.
pause
exit /b 0

:no_python
echo Python was not found. Install Python 3.9 or newer and select Add Python to PATH.
pause
exit /b 1

:bad_python
echo Python 3.9 or newer with SSL and Tkinter is required.
echo Install a complete Python 3.9 or newer distribution and try again.
pause
exit /b 1

:venv_failed
echo Could not create SwimCast's private Python environment in this folder.
echo Move SwimCast to a writable folder and try again.
pause
exit /b 1

:install_failed
echo Package installation into SwimCast's private environment failed.
echo Check the messages above and try again.
pause
exit /b 1

