@echo off
REM Check that Docker Desktop is installed and running; say how to get it if not.

docker --version >nul 2>&1
if errorlevel 1 goto not_installed

docker info >nul 2>&1
if errorlevel 1 goto not_running

echo Docker is ready:
docker --version
echo.
echo Next: installer\windows\run-docker.bat
pause
exit /b 0

:not_running
echo Docker Desktop is installed but not running.
echo Start it from the Start menu, wait until it says it is running,
echo then run this script again.
pause
exit /b 1

:not_installed
echo Docker Desktop is not installed.
echo.
echo   1. Download it from https://www.docker.com/products/docker-desktop/
echo   2. Run the installer and restart the computer if it asks to
echo   3. Start Docker Desktop from the Start menu
echo   4. Run this script again
echo.
echo It needs Windows 10 or 11 (64 bit) with WSL 2, and virtualization
echo enabled in the BIOS. More help: https://docs.docker.com/desktop/setup/install/windows-install/
pause
exit /b 1
