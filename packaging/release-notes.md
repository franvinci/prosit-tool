## Getting it

| | |
|---|---|
| **Windows** | Download `prosit-tool-…-windows-x86_64.zip`, unpack it and double-click `prosit-tool.exe`. |
| **macOS** | Download `prosit-tool-…-macos-arm64.tar.gz` (Apple Silicon) or `prosit-tool-…-macos-x86_64.tar.gz` (Intel) and unpack it. Before the first start, see `README.txt` inside. |
| **Linux** | Download `prosit-tool-…-linux-x86_64.tar.gz`, unpack it and run `./prosit-tool`. |
| **Docker** | `docker run --rm -p 127.0.0.1:5050:5050 -v prosit-data:/data ghcr.io/franvinci/prosit-tool` |
| **pip** | With Python 3.10 to 3.12: download the `.whl` file below and `pipx install` it (or `uv tool install`, or `pip install` in an environment of its own). |

Then open http://localhost:5050 (the executables open it for you).

The executables are not signed: Windows and macOS ask for a confirmation the first time. `README.txt`, inside each archive, says what to do.

## Licences

ProSiT Tool is released under the MIT License. The executables and the Docker image also contain Python and the libraries the tool needs, each under its own licence; some of them (pm4py, CVXOPT) are under the GNU Affero General Public License or the GNU General Public License, so those packages as a whole are distributed under the GNU AGPL, version 3 or later. `THIRD-PARTY-NOTICES.txt`, inside each of them, lists every component. The source of the tool is the "Source code" archive below; the source of pm4py and CVXOPT is in `prosit-tool-…-copyleft-sources.tar.gz`.
