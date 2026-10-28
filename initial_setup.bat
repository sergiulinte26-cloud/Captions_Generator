@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0env\Scripts\python.exe"

if not exist "%~dp0requirements.txt" (
	echo requirements.txt was not found beside this script.
	goto :failed
)

if exist "%PYTHON%" goto :install

py -3 --version >nul 2>&1
if not errorlevel 1 (
	echo Creating the env virtual environment...
	py -3 -m venv "%~dp0env"
	if errorlevel 1 goto :failed
	goto :install
)

python --version >nul 2>&1
if errorlevel 1 (
	echo Python 3 was not found. Install Python 3 and reopen this script.
	goto :failed
)

echo Creating the env virtual environment...
python -m venv "%~dp0env"
if errorlevel 1 goto :failed

:install
"%PYTHON%" -c "import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] < (3, 13) else 1)"
if errorlevel 1 (
	echo This setup requires Python 3.10, 3.11, or 3.12 for CPU alignment.
	echo Recreate env with a supported Python version, then run this script again.
	goto :failed
)
echo Installing application dependencies and PyInstaller...
"%PYTHON%" -m pip install -r "%~dp0requirements.txt" PyInstaller
if errorlevel 1 goto :failed

echo.
echo Setup complete.
echo Double-click run_app.bat to start the application.
echo Double-click build_exe.bat to build the executable and sharing ZIP.
pause
exit /b 0

:failed
echo.
echo Setup failed. Check the error above. Internet access is required for installation.
pause
exit /b 1
