#!/bin/bash

# ProSiT Docker Setup Script for Ubuntu
# This script installs Docker and Docker Compose, then sets up the ProSiT application

set -e  # Exit on any error

echo "========================================"
echo "ProSiT Docker Setup for Ubuntu"
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

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    print_error "Please do not run this script as root. It will use sudo when needed."
    exit 1
fi

# Update package list
print_status "Updating package list..."
sudo apt-get update

# Install required packages
print_status "Installing required packages..."
sudo apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    software-properties-common

# Add Docker's official GPG key
print_status "Adding Docker's official GPG key..."
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

# Add Docker repository
print_status "Adding Docker repository..."
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Update package list again
print_status "Updating package list with Docker repository..."
sudo apt-get update

# Install Docker
print_status "Installing Docker..."
sudo apt-get install -y docker-ce docker-ce-cli containerd.io

# Add current user to docker group
print_status "Adding current user to docker group..."
sudo usermod -aG docker $USER

# Install Docker Compose
print_status "Installing Docker Compose..."
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Start Docker service
print_status "Starting Docker service..."
sudo systemctl start docker
sudo systemctl enable docker

# Verify installations
print_status "Verifying Docker installation..."
if docker --version &> /dev/null; then
    print_success "Docker installed successfully: $(docker --version)"
else
    print_error "Docker installation failed"
    exit 1
fi

print_status "Verifying Docker Compose installation..."
if docker-compose --version &> /dev/null; then
    print_success "Docker Compose installed successfully: $(docker-compose --version)"
else
    print_error "Docker Compose installation failed"
    exit 1
fi

# Make scripts executable
print_status "Making scripts executable..."
chmod +x "$(dirname "$0")/run-docker.sh"
chmod +x "$(dirname "$0")/stop-docker.sh"

echo
echo "========================================"
echo "Setup Complete!"
echo "========================================"
print_success "Docker and Docker Compose have been installed successfully!"
echo
print_warning "IMPORTANT: You need to log out and log back in (or restart your system)"
print_warning "for the docker group changes to take effect."
echo
echo "After logging back in, you can:"
echo "1. Run the application: $(dirname "$0")/run-docker.sh"
echo "2. Stop the application: $(dirname "$0")/stop-docker.sh"
echo
echo "Or use Docker Compose directly:"
echo "  Start: docker-compose up -d"
echo "  Stop:  docker-compose down"
echo
print_status "Setup completed successfully!"
