@echo off
REM ProSiT Docker Runner for Windows
REM This script helps you run the ProSiT application using Docker

echo ========================================
echo ProSiT Docker Runner for Windows
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

echo Docker is running. Proceeding with setup...
echo.

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

echo Starting ProSiT application...
echo.

REM Stop any existing containers
echo Stopping any existing containers...
docker-compose down >nul 2>&1

REM Build and start the application
echo Building and starting the application...
docker-compose up -d --build

if %errorlevel% neq 0 (
    echo ERROR: Failed to start the application.
    echo Check the error messages above.
    pause
    exit /b 1
)

echo.
echo ========================================
echo Application Status
echo ========================================
docker-compose ps

echo.
echo ========================================
echo Access Information
echo ========================================
echo Application URL: http://localhost:5000
echo.
echo To view logs: docker-compose logs -f
echo To stop: docker-compose down
echo To restart: docker-compose restart
echo.

REM Wait a moment for the application to start
echo Waiting for application to start...
timeout /t 10 /nobreak >nul

REM Check if application is responding
echo Checking application health...
curl -s -o nul -w "%%{http_code}" http://localhost:5000 > temp_status.txt
set /p status=<temp_status.txt
del temp_status.txt

if "%status%"=="200" (
    echo ✓ Application is running successfully!
    echo ✓ You can now access it at: http://localhost:5000
) else (
    echo ⚠ Application may still be starting up.
    echo Please wait a moment and try accessing: http://localhost:5000
)

echo.
echo Press any key to open the application in your browser...
pause >nul

REM Try to open the application in the default browser
start http://localhost:5000

echo.
echo Application opened in browser. You can close this window.
echo To stop the application later, run: docker-compose down
pause
