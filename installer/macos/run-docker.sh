#!/bin/bash
# Start ProSiT with Docker and open it in the browser.
#
#   installer/macos/run-docker.sh            use the published image
#   installer/macos/run-docker.sh --build    build the image from this checkout instead

set -e

URL="http://localhost:5050"
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

if ! command -v docker > /dev/null 2>&1; then
    echo "Docker is not installed. Run installer/macos/setup-macos.sh first." >&2
    exit 1
fi
if ! docker info > /dev/null 2>&1; then
    echo "Docker is installed but does not answer." >&2
    echo "Start Docker Desktop (Applications, or Spotlight) and wait until the" >&2
    echo "whale in the menu bar stops moving, then run this script again." >&2
    exit 1
fi
if ! docker compose version > /dev/null 2>&1; then
    echo "Docker Compose is missing ('docker compose' does not work)." >&2
    echo "It comes with Docker Desktop: update Docker Desktop." >&2
    exit 1
fi

echo "Starting ProSiT (the first time, the image has to be downloaded)..."
if ! docker compose up -d --wait "$@"; then
    echo >&2
    echo "ProSiT did not start. See what it says with:  docker compose logs" >&2
    exit 1
fi

echo
echo "ProSiT is running at $URL"
echo "To stop it:  installer/macos/stop-docker.sh"
if command -v open > /dev/null 2>&1; then
    open "$URL" > /dev/null 2>&1 || true
fi
