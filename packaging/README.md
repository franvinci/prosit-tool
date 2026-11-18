# Packaging

What turns the source in this repository into the forms of the tool that
people install. The release workflow (`.github/workflows/release.yml`) runs
all of it when a tag `v<version>` is pushed; every step can also be run by
hand.

| File | What it is |
|---|---|
| `constraints.txt` | The version of every dependency that a release is tested with and built from, for Python 3.10 to 3.12 on every system. |
| `smoke_test.py` | Starts a packaged ProSiT and takes it through a whole session: upload, discovery, simulation, results. Standard library only. |
| `prosit-tool.spec`, `launcher.py` | The PyInstaller recipe of the executable, and what the executable runs. |
| `build_executable.py` | Builds the executable for the system it runs on, adds the notices, tries it and packs it. |
| `requirements-build.txt` | PyInstaller, at the version the executables are built with. |
| `README-executable.txt` | The `README.txt` that goes next to the executable. |
| `third_party_notices.py` | Writes `THIRD-PARTY-NOTICES.txt`: every component of a packaged ProSiT with its licence. |
| `copyleft_sources.py` | Downloads the source of the GPL and AGPL packages that the executables and the image contain. |
| `release-notes.md` | The beginning of the notes of every GitHub Release. |

## The versions of the dependencies

`pyproject.toml` says which versions the tool accepts; `constraints.txt` says
which ones a release was tested with. To move to newer ones:

```bash
uv pip compile pyproject.toml --extra dev --universal --python-version 3.10 -o packaging/constraints.txt
```

then run the tests on Python 3.10, 3.11 and 3.12.

## The pip package

```bash
python -m build
python packaging/smoke_test.py prosit-tool        # in an environment where the wheel is installed
```

## The executable

In an environment of its own, on the system the executable is for:

```bash
pip install -c packaging/constraints.txt . -r packaging/requirements-build.txt
python packaging/build_executable.py
```

The result is `dist/prosit-tool-<version>-<system>-<machine>.zip` (Windows) or
`.tar.gz`. An executable only runs on the system and the processor it was
built on, which is why the release workflow builds one on each.

## The Docker image

```bash
docker build -t prosit-tool .
docker run --rm -d -p 127.0.0.1:5050:5050 -v prosit-data:/data prosit-tool
python packaging/smoke_test.py --url http://localhost:5050
```

## Licences

The source tree and the pip package include only the libraries of the page,
described in `THIRD-PARTY-LICENSES`. The executables and the image contain
every Python dependency as well, some of them under the GNU GPL or AGPL: each
carries the `THIRD-PARTY-NOTICES.txt` written by `third_party_notices.py`, and
the release carries the source of those packages (`copyleft_sources.py`).
