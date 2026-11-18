@echo off
REM Stop the ProSiT started with run-docker.bat. Its data stays where it is
REM (uploads, simulations and instance, in the folder of the project).

setlocal
cd /d "%~dp0..\.."

docker info >nul 2>&1
if errorlevel 1 goto no_docker
docker compose version >nul 2>&1
if errorlevel 1 goto no_compose

docker compose down
if errorlevel 1 goto not_stopped

echo.
echo ProSiT is stopped. To start it again: installer\windows\run-docker.bat
exit /b 0

:not_stopped
echo.
echo ProSiT could not be stopped: see the messages above.
pause
exit /b 1

:no_docker
echo Docker is not installed, or Docker Desktop is not running.
echo Start Docker Desktop, wait until it says it is running, and try again.
echo If it is not installed: installer\windows\setup-windows.bat
pause
exit /b 1

:no_compose
echo Docker Compose is missing ("docker compose" does not work).
echo It comes with Docker Desktop: update Docker Desktop.
pause
exit /b 1
