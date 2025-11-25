#!/bin/bash

# ProSiT Docker Runner for macOS
# This script helps you run the ProSiT application using Docker

set -e  # Exit on any error

echo "========================================"
echo "ProSiT Docker Runner for macOS"
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

# Check if Docker is installed and running
print_status "Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker Desktop first."
    echo "Run the setup script: $(dirname "$0")/setup-macos.sh"
    echo "Or download from: https://www.docker.com/products/docker-desktop/"
    exit 1
fi

if ! docker info &> /dev/null; then
    print_error "Docker is not running. Please start Docker Desktop."
    echo "You can start Docker Desktop from:"
    echo "  - Applications folder"
    echo "  - Spotlight search (Cmd+Space, then type 'Docker')"
    echo "  - Launchpad"
    echo
    echo "Wait for the whale icon to appear in the menu bar and become steady."
    exit 1
fi

print_success "Docker is running"

# Check if docker-compose is available
print_status "Checking Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    print_error "Docker Compose is not installed. Please install Docker Desktop first."
    echo "Docker Compose should be included with Docker Desktop."
    echo "Run the setup script: $(dirname "$0")/setup-macos.sh"
    exit 1
fi

print_success "Docker Compose is available"

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Change to project root directory
cd "$PROJECT_ROOT"

# Check if docker-compose.yml exists
if [ ! -f "docker-compose.yml" ]; then
    print_error "docker-compose.yml not found in project root directory."
    echo "Expected location: $PROJECT_ROOT/docker-compose.yml"
    exit 1
fi

print_status "Starting ProSiT application..."

# Stop any existing containers
print_status "Stopping any existing containers..."
docker-compose down &> /dev/null || true

# Build and start the application
print_status "Building and starting the application..."
print_status "This may take a few minutes on first run as Docker builds the container..."
if ! docker-compose up -d --build; then
    print_error "Failed to start the application."
    echo "Check the error messages above."
    echo
    echo "Common solutions:"
    echo "1. Ensure Docker Desktop has sufficient memory allocated (4GB+)"
    echo "2. Try restarting Docker Desktop"
    echo "3. Check if you have enough disk space"
    exit 1
fi

echo
echo "========================================"
echo "Application Status"
echo "========================================"
docker-compose ps

echo
echo "========================================"
echo "Access Information"
echo "========================================"
echo "Application URL: http://localhost:5050"
echo
echo "Useful commands:"
echo "  View logs:    docker-compose logs -f"
echo "  Stop:         docker-compose down"
echo "  Restart:      docker-compose restart"
echo

# Wait for application to start
print_status "Waiting for application to start..."
sleep 10

# Check if application is responding
print_status "Checking application health..."
if command -v curl &> /dev/null; then
    status_code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5050 || echo "000")
    
    if [ "$status_code" = "200" ]; then
        print_success "Application is running successfully!"
        print_success "You can now access it at: http://localhost:5050"
    else
        print_warning "Application may still be starting up."
        print_warning "Please wait a moment and try accessing: http://localhost:5050"
    fi
else
    print_warning "curl not available. Cannot check application health."
    print_warning "Please manually check: http://localhost:5050"
fi

echo
echo "========================================"
echo "Next Steps"
echo "========================================"
echo "1. Open your web browser"
echo "2. Navigate to: http://localhost:5050"
echo "3. Start using the ProSiT application!"
echo
echo "To stop the application later, run: $(dirname "$0")/stop-docker.sh"
echo

# Try to open the application in the default browser
if command -v open &> /dev/null; then
    print_status "Opening application in default browser..."
    open http://localhost:5050 &> /dev/null || true
else
    print_warning "Could not automatically open browser. Please manually navigate to http://localhost:5050"
fi

print_success "Setup complete! The application should be running at http://localhost:5050"
