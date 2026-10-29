@echo off
rem Keep this file ASCII-only: cmd parses .bat files in the system codepage (CP949),
rem so non-ASCII text can corrupt the following lines.
rem Run once (and again after updates): installs packages and creates the desktop/start menu shortcuts.
setlocal
cd /d "%~dp0"

rem The venv lives outside OneDrive to avoid syncing thousands of files.
if "%LOCALAPPDATA%"=="" goto fail_env
set "VENV=%LOCALAPPDATA%\ColdMailSender\venv"
if exist "%VENV%\Scripts\python.exe" goto install

where python >nul 2>nul || goto fail_python
echo [ColdMail Sender] Creating Python environment...
python -m venv "%VENV%" || goto fail_install

:install
echo [ColdMail Sender] Installing packages...
"%VENV%\Scripts\python.exe" -m pip install -q -r requirements.txt || goto fail_install
"%VENV%\Scripts\python.exe" install.py || goto fail_install
pause
exit /b 0

:fail_env
echo LOCALAPPDATA is not set. Cannot decide where to install.
pause
exit /b 1

:fail_python
echo Python was not found. Install Python 3.10+ from https://www.python.org and check "Add to PATH".
pause
exit /b 1

:fail_install
echo.
echo Setup failed. Delete this folder and run setup.bat again:
echo   %VENV%
pause
exit /b 1
