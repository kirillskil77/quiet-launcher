@echo off
setlocal
cd /d "%~dp0"
echo === Quiet Launcher build ===
echo.

py -3.8 --version >nul 2>&1
if errorlevel 1 goto nopython

if not exist .venv-build\Scripts\python.exe py -3.8 -m venv .venv-build
if errorlevel 1 goto fail
set PY=.venv-build\Scripts\python.exe

%PY% -m pip install --upgrade pip
if errorlevel 1 goto fail
%PY% -m pip install -r requirements-build.txt
if errorlevel 1 goto fail
%PY% -m PyInstaller --noconfirm --clean --windowed --name QuietLauncher --collect-data certifi --icon assets\icon.ico --add-data "assets;assets" main.py
if errorlevel 1 goto fail

%PY% -c "from ql import APP_VERSION; print(APP_VERSION)" > version.tmp
set /p VER=<version.tmp
del version.tmp

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if "%ISCC%"=="" goto noinno

"%ISCC%" /DAppVersion=%VER% installer\QuietLauncher.iss
if errorlevel 1 goto fail
echo.
echo DONE. Installer: dist\QuietLauncher-Setup.exe
goto end

:noinno
echo.
echo Program built: dist\QuietLauncher\QuietLauncher.exe
echo Installer NOT built because Inno Setup 6 is not installed.
echo Install it from https://jrsoftware.org/isdl.php and run build.bat again.
goto end

:nopython
echo Python 3.8 not found.
echo Install it from https://www.python.org/downloads/release/python-3810/
echo and tick "Add Python to PATH" in the installer.
goto end

:fail
echo.
echo BUILD FAILED. Take a screenshot of this window and send it.

:end
echo.
pause
endlocal
