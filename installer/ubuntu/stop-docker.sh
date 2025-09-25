#!/bin/bash

# ProSiT Docker Stopper for Ubuntu/Linux
# This script stops the ProSiT Docker containers

set -e  # Exit on any error

echo "========================================"
echo "ProSiT Docker Stopper for Ubuntu/Linux"
echo "========================================"
echo

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is installed and running
print_status "Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed."
    exit 1
fi

if ! docker info &> /dev/null; then
    print_error "Docker is not running. Please start Docker service."
    echo "Try: sudo systemctl start docker"
    echo "Or: sudo service docker start"
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    print_error "Docker Compose is not installed."
    exit 1
fi

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

print_status "Stopping ProSiT application..."

# Stop and remove containers
if ! docker-compose down; then
    print_error "Failed to stop the application."
    echo "Check the error messages above."
    exit 1
fi

echo
print_success "Application stopped successfully!"
echo
echo "To start the application again, run: ./run-docker.sh"
echo
