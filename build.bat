@echo off
rem Keep this file ASCII-only: cmd parses .bat files in the system codepage (CP949).
rem Builds the installer for colleagues: release\ColdMailSender_Setup_<version>.exe
rem Needs: setup.bat run once (venv), Inno Setup 6 (winget install JRSoftware.InnoSetup --scope user).
setlocal
cd /d "%~dp0"

if "%LOCALAPPDATA%"=="" goto fail_env
set "VENV=%LOCALAPPDATA%\ColdMailSender\venv"
rem Build files live outside OneDrive to avoid syncing them.
set "WORK=%LOCALAPPDATA%\ColdMailSender\build"
if not exist "%VENV%\Scripts\python.exe" goto fail_venv

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" goto fail_iscc

echo [1/2] Building exe...
"%VENV%\Scripts\python.exe" -m pip install -q -r requirements.txt pyinstaller || goto fail
"%VENV%\Scripts\python.exe" -m PyInstaller launcher.pyw --name ColdMailSender --windowed --noconfirm --clean ^
  --icon "%~dp0static\app.ico" --add-data "%~dp0static;static" --add-data "%~dp0samples;samples" ^
  --collect-submodules dns --collect-submodules markdown --collect-submodules keyring ^
  --workpath "%WORK%\work" --specpath "%WORK%" --distpath "%WORK%\dist" || goto fail

echo [2/2] Building installer...
"%ISCC%" /Q /O"%~dp0release" /DDist="%WORK%\dist\ColdMailSender" installer.iss || goto fail
echo.
echo Done: %~dp0release
pause
exit /b 0

:fail_env
echo LOCALAPPDATA is not set.
pause
exit /b 1

:fail_venv
echo Run setup.bat first.
pause
exit /b 1

:fail_iscc
echo Inno Setup 6 not found. Install it: winget install JRSoftware.InnoSetup --scope user
pause
exit /b 1

:fail
echo.
echo Build failed. See the messages above.
pause
exit /b 1
