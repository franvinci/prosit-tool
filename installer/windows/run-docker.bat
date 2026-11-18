@echo off
REM Start ProSiT with Docker and open it in the browser.
REM
REM   installer\windows\run-docker.bat            use the published image
REM   installer\windows\run-docker.bat --build    build the image from this checkout instead

setlocal
set "URL=http://localhost:5050"
cd /d "%~dp0..\.."

docker info >nul 2>&1
if errorlevel 1 goto no_docker
docker compose version >nul 2>&1
if errorlevel 1 goto no_compose

echo Starting ProSiT (the first time, the image has to be downloaded)...
docker compose up -d --wait %*
if errorlevel 1 goto not_started

echo.
echo ProSiT is running at %URL%
echo To stop it: installer\windows\stop-docker.bat
start "" "%URL%"
exit /b 0

:not_started
echo.
echo ProSiT did not start. See what it says with: docker compose logs
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
