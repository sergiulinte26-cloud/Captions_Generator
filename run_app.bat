@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0env\Scripts\python.exe"
if not exist "%PYTHON%" (
	echo Python was not found at "%PYTHON%".
	pause
	exit /b 1
)
"%PYTHON%" "%~dp0main.py"
set "APP_EXIT_CODE=%ERRORLEVEL%"
if not "%APP_EXIT_CODE%"=="0" (
	echo.
	echo Application exited with error code %APP_EXIT_CODE%.
	pause
)
exit /b %APP_EXIT_CODE%
