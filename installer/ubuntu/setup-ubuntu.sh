#!/bin/bash
# Install Docker Engine and its Compose plugin on Ubuntu, from Docker's own
# package repository (https://docs.docker.com/engine/install/ubuntu/).
# Nothing is installed when Docker is already there.

set -e

if [ "$(id -u)" -eq 0 ]; then
    echo "Run this script as your own user: it asks for sudo when it needs it." >&2
    exit 1
fi

if ! command -v docker > /dev/null 2>&1; then
    echo "Installing Docker Engine and the Compose plugin..."
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    # shellcheck disable=SC1091
    codename="$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")"
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $codename stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo systemctl enable --now docker
elif ! docker compose version > /dev/null 2>&1; then
    echo "Docker is installed ($(docker --version)), but 'docker compose' is not." >&2
    echo "Add it with the package of the Docker you have:" >&2
    echo "  - Docker from docker.com:   sudo apt-get install docker-compose-plugin" >&2
    echo "  - Docker from Ubuntu:       sudo apt-get install docker-compose-v2" >&2
    exit 1
else
    echo "Docker is already installed: $(docker --version)"
fi

if ! id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
    sudo usermod -aG docker "$USER"
    echo
    echo "Your user is now in the 'docker' group."
    echo "Log out and in again (or restart) before starting ProSiT."
fi

echo
echo "Next:  installer/ubuntu/run-docker.sh"
