#!/bin/bash
# Stop the ProSiT started with run-docker.sh. Its data stays where it is
# (uploads/, simulations/ and instance/, in the folder of the project).

set -e

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

docker compose down
echo
echo "ProSiT is stopped. To start it again:  installer/macos/run-docker.sh"
