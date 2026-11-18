#!/bin/bash
# Check that Docker Desktop is installed and running; say how to get it if not.

if ! command -v docker > /dev/null 2>&1; then
    echo "Docker Desktop is not installed."
    echo
    echo "  1. Download it from https://www.docker.com/products/docker-desktop/"
    echo "     (or, with Homebrew:  brew install --cask docker)"
    echo "  2. Open the .dmg and drag Docker to the Applications folder"
    echo "  3. Start Docker from Applications and follow its first-run steps"
    echo "  4. Run this script again"
    exit 1
fi

if ! docker info > /dev/null 2>&1; then
    echo "Docker Desktop is installed but not running."
    echo "Start it (Applications, or Spotlight) and wait until the whale in the"
    echo "menu bar stops moving, then run this script again."
    exit 1
fi

echo "Docker is ready: $(docker --version)"
echo
echo "Next:  installer/macos/run-docker.sh"
