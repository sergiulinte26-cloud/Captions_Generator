@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0env\Scripts\python.exe"
if not exist "%PYTHON%" (
	echo Python was not found at "%PYTHON%".
	pause
	exit /b 1
)
"%PYTHON%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
	echo PyInstaller is not installed.
	echo Run: "%PYTHON%" -m pip install PyInstaller
	pause
	exit /b 1
)
"%PYTHON%" -m PyInstaller --clean --noconfirm "%~dp0CaptionsGenerator.spec"
if errorlevel 1 (
	echo Build failed. See the errors above.
	pause
	exit /b 1
)
echo.
echo Build complete: %~dp0dist\CaptionsGenerator\CaptionsGenerator.exe
echo Creating distribution ZIP...
"%PYTHON%" -c "import os, shutil, zipfile; archive = shutil.make_archive('dist/CaptionsGenerator-Windows-x64.tmp', 'zip', root_dir='dist', base_dir='CaptionsGenerator'); z = zipfile.ZipFile(archive); bad = z.testzip(); z.close(); bad is None or exit('ZIP verification failed: ' + bad); os.replace(archive, 'dist/CaptionsGenerator-Windows-x64.zip')"
if errorlevel 1 (
	echo ZIP creation failed. Do not share an older ZIP as the new build.
	pause
	exit /b 1
)
echo.
echo Package ready: %~dp0dist\CaptionsGenerator-Windows-x64.zip
echo Share this ZIP. Extract the entire archive before running the executable.
pause
exit /b 0
