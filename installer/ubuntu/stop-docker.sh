#!/bin/bash
# Stop the ProSiT started with run-docker.sh. Its data stays where it is
# (uploads/, simulations/ and instance/, in the folder of the project).

set -e

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

if ! command -v docker > /dev/null 2>&1; then
    echo "Docker is not installed. Run installer/ubuntu/setup-ubuntu.sh first." >&2
    exit 1
fi
if ! docker info > /dev/null 2>&1; then
    echo "Docker is installed but does not answer." >&2
    echo "  - if it is not running:  sudo systemctl start docker" >&2
    echo "  - if it is, your user is not in the 'docker' group yet: log out and" >&2
    echo "    in again after running installer/ubuntu/setup-ubuntu.sh" >&2
    exit 1
fi
if ! docker compose version > /dev/null 2>&1; then
    echo "Docker Compose is missing ('docker compose' does not work)." >&2
    echo "Install the docker-compose-plugin package (docker-compose-v2 on Ubuntu's own Docker)." >&2
    exit 1
fi

docker compose down
echo
echo "ProSiT is stopped. To start it again:  installer/ubuntu/run-docker.sh"
