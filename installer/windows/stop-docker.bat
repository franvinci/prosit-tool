@echo off
REM ProSiT Docker Stopper for Windows
REM This script stops the ProSiT Docker containers

echo ========================================
echo ProSiT Docker Stopper for Windows
echo ========================================
echo.

REM Check if Docker is running
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Docker is not running or not installed.
    echo Please start Docker Desktop and try again.
    pause
    exit /b 1
)

REM Get the directory where this script is located
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%..\..\"

REM Change to project root directory
cd /d "%PROJECT_ROOT%"

REM Check if docker-compose.yml exists
if not exist "docker-compose.yml" (
    echo ERROR: docker-compose.yml not found in project root directory.
    echo Expected location: %PROJECT_ROOT%docker-compose.yml
    pause
    exit /b 1
)

echo Stopping ProSiT application...
echo.

REM Stop and remove containers
docker-compose down

if %errorlevel% neq 0 (
    echo ERROR: Failed to stop the application.
    echo Check the error messages above.
    pause
    exit /b 1
)

echo.
echo ✓ Application stopped successfully!
echo.
echo To start the application again, run: run-docker.bat
echo.
pause
