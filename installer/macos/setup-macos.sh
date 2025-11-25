#!/bin/bash

# ProSiT Docker Setup Script for macOS
# This script installs Docker Desktop and sets up the ProSiT application

set -e  # Exit on any error

echo "========================================"
echo "ProSiT Docker Setup for macOS"
echo "========================================"
echo

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker Desktop is already installed
print_status "Checking for existing Docker installation..."
if command -v docker &> /dev/null; then
    print_success "Docker is already installed: $(docker --version)"
    echo
    
    print_status "Checking if Docker Desktop is running..."
    if docker info &> /dev/null; then
        print_success "Docker Desktop is running!"
        echo
        echo "You can now run the ProSiT application using:"
        echo "  $(dirname "$0")/run-docker.sh"
        echo
        exit 0
    else
        print_warning "Docker Desktop is installed but not running."
        echo "Please start Docker Desktop and try again."
        echo "You can start Docker Desktop from:"
        echo "  - Applications folder"
        echo "  - Spotlight search (Cmd+Space, then type 'Docker')"
        echo "  - Launchpad"
        echo
        exit 1
    fi
fi

print_status "Docker Desktop is not installed."
echo

echo "========================================"
echo "Installation Instructions"
echo "========================================"
echo

print_status "To install Docker Desktop on macOS:"
echo
echo "1. Download Docker Desktop from:"
echo "   https://www.docker.com/products/docker-desktop/"
echo
echo "2. Open the downloaded .dmg file"
echo
echo "3. Drag Docker.app to the Applications folder"
echo
echo "4. Start Docker Desktop from:"
echo "   - Applications folder"
echo "   - Spotlight search (Cmd+Space, then type 'Docker')"
echo "   - Launchpad"
echo
echo "5. Follow the setup wizard when Docker Desktop starts"
echo
echo "6. Wait for Docker Desktop to fully start (you'll see a whale icon in the menu bar)"
echo
echo "7. Run this script again to verify the installation"
echo

echo "========================================"
echo "System Requirements"
echo "========================================"
echo
echo "Docker Desktop requires:"
echo "- macOS 10.15 or later"
echo "- 4GB RAM (8GB recommended)"
echo "- Virtualization support (Intel or Apple Silicon)"
echo "- At least 2GB free disk space"
echo

# Check macOS version
print_status "Checking macOS version..."
macos_version=$(sw_vers -productVersion)
print_status "Current macOS version: $macos_version"

# Check if running on Apple Silicon or Intel
if [[ $(uname -m) == "arm64" ]]; then
    print_status "Detected Apple Silicon Mac (M1/M2/M3)"
    echo "Docker Desktop will run natively on Apple Silicon"
else
    print_status "Detected Intel Mac"
    echo "Docker Desktop will run with Rosetta 2 if needed"
fi

echo

echo "========================================"
echo "Alternative Installation Methods"
echo "========================================"
echo

print_status "You can also install Docker using:"
echo
echo "1. Homebrew (if you have it installed):"
echo "   brew install --cask docker"
echo
echo "2. Direct download from Docker website:"
echo "   https://desktop.docker.com/mac/main/amd64/Docker.dmg"
echo "   (Intel Macs)"
echo "   https://desktop.docker.com/mac/main/arm64/Docker.dmg"
echo "   (Apple Silicon Macs)"
echo

echo "========================================"
echo "After Installation"
echo "========================================"
echo
echo "Once Docker Desktop is installed and running:"
echo
echo "1. Run: $(dirname "$0")/run-docker.sh"
echo "   This will start the ProSiT application"
echo
echo "2. Open your browser and go to: http://localhost:5050"
echo
echo "3. To stop the application, run: $(dirname "$0")/stop-docker.sh"
echo

echo "========================================"
echo "Troubleshooting"
echo "========================================"
echo
echo "If you encounter issues:"
echo
echo "1. Make sure Docker Desktop is fully started"
echo "   - Look for the whale icon in the menu bar"
echo "   - The icon should be steady (not animated)"
echo
echo "2. Check Docker Desktop preferences:"
echo "   - Click the Docker icon in the menu bar"
echo "   - Go to Preferences > Resources"
echo "   - Ensure sufficient memory allocation (4GB+)"
echo
echo "3. Restart Docker Desktop if needed:"
echo "   - Quit Docker Desktop from the menu bar"
echo "   - Restart from Applications folder"
echo
echo "4. Check system requirements:"
echo "   - Ensure virtualization is enabled"
echo "   - Check available disk space and RAM"
echo
echo "For more help, visit: https://docs.docker.com/desktop/mac/"
echo

# Make scripts executable
print_status "Making scripts executable..."
chmod +x "$(dirname "$0")/run-docker.sh"
chmod +x "$(dirname "$0")/stop-docker.sh"

echo
print_status "Setup script completed!"
echo "Please install Docker Desktop and then run this script again to verify the installation."
echo
