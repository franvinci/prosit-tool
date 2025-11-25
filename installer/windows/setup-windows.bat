@echo off
REM ProSiT Docker Setup Script for Windows
REM This script helps you set up Docker Desktop for the ProSiT application

echo ========================================
echo ProSiT Docker Setup for Windows
echo ========================================
echo.

REM Check if Docker Desktop is already installed
docker --version >nul 2>&1
if %errorlevel% equ 0 (
    echo Docker is already installed: 
    docker --version
    echo.
    echo Checking if Docker Desktop is running...
    docker info >nul 2>&1
    if %errorlevel% equ 0 (
        echo ✓ Docker Desktop is running!
        echo.
        echo You can now run the ProSiT application using:
        echo   run-docker.bat
        echo.
        pause
        exit /b 0
    ) else (
        echo ⚠ Docker Desktop is installed but not running.
        echo Please start Docker Desktop and try again.
        echo.
        pause
        exit /b 1
    )
)

echo Docker Desktop is not installed.
echo.
echo ========================================
echo Installation Instructions
echo ========================================
echo.
echo To install Docker Desktop on Windows:
echo.
echo 1. Download Docker Desktop from:
echo    https://www.docker.com/products/docker-desktop/
echo.
echo 2. Run the installer and follow the setup wizard
echo.
echo 3. Restart your computer when prompted
echo.
echo 4. Start Docker Desktop from the Start menu
echo.
echo 5. Wait for Docker Desktop to fully start (you'll see a green icon in the system tray)
echo.
echo 6. Run this script again to verify the installation
echo.
echo ========================================
echo System Requirements
echo ========================================
echo.
echo Docker Desktop requires:
echo - Windows 10 64-bit: Pro, Enterprise, or Education (Build 15063 or later)
echo - Windows 11 64-bit: Home or Pro version 21H2 or higher
echo - WSL 2 feature enabled
echo - Virtualization enabled in BIOS
echo - At least 4GB RAM
echo.
echo ========================================
echo After Installation
echo ========================================
echo.
echo Once Docker Desktop is installed and running:
echo.
echo 1. Run: run-docker.bat
echo    This will start the ProSiT application
echo.
echo 2. Open your browser and go to: http://localhost:5050
echo.
echo 3. To stop the application, run: stop-docker.bat
echo.
echo ========================================
echo Troubleshooting
echo ========================================
echo.
echo If you encounter issues:
echo.
echo 1. Make sure Windows features are enabled:
echo    - Hyper-V (if available)
echo    - Windows Subsystem for Linux
echo    - Virtual Machine Platform
echo.
echo 2. Enable virtualization in BIOS/UEFI settings
echo.
echo 3. Restart your computer after enabling features
echo.
echo 4. Check Docker Desktop logs if it fails to start
echo.
echo For more help, visit: https://docs.docker.com/desktop/windows/
echo.
pause
