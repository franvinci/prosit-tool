#!/usr/bin/env python3
"""Build the ProSiT executable for the system this runs on, try it and pack it.

    python packaging/build_executable.py

It needs an environment where the tool and PyInstaller are installed, at the
versions the release is tested with:

    pip install -c packaging/constraints.txt . -r packaging/requirements-build.txt

The steps: PyInstaller makes the folder (prosit-tool.spec); the licence and
the notices of everything inside are added to it; the program is started and
taken through a whole session (smoke_test.py); the folder is packed as
prosit-tool-<version>-<system>-<machine>.zip (Windows) or .tar.gz, with its
SHA-256 next to it.
"""

import argparse
import hashlib
import platform
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NAME = 'prosit-tool'

SYSTEMS = {'Windows': 'windows', 'Darwin': 'macos', 'Linux': 'linux'}
MACHINES = {'amd64': 'x86_64', 'x86_64': 'x86_64', 'arm64': 'arm64', 'aarch64': 'arm64'}


def run(command):
    print('>', ' '.join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True)


def folder_size(folder):
    return sum(path.stat().st_size for path in folder.rglob('*') if path.is_file() and not path.is_symlink())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist',
                        help='where the folder and the archive are written (default: dist)')
    parser.add_argument('--work-dir', type=Path, default=ROOT / 'build' / 'pyinstaller',
                        help='where PyInstaller keeps its intermediate files (default: build/pyinstaller)')
    parser.add_argument('--skip-test', action='store_true', help='do not start the program to try it')
    args = parser.parse_args(argv)

    version = metadata.version(NAME)
    system = SYSTEMS.get(platform.system(), platform.system().lower())
    machine = MACHINES.get(platform.machine().lower(), platform.machine().lower())
    output = args.output_dir.resolve()
    folder = output / NAME
    program = folder / (NAME + ('.exe' if system == 'windows' else ''))

    run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
         '--distpath', output, '--workpath', args.work_dir.resolve(), HERE / 'prosit-tool.spec'])
    if not program.is_file():
        sys.exit(f'PyInstaller did not make {program}')

    # What whoever receives the folder is entitled to find in it.
    shutil.copyfile(ROOT / 'LICENSE', folder / 'LICENSE')
    readme = (HERE / 'README-executable.txt').read_text(encoding='utf-8').replace('{version}', version)
    (folder / 'README.txt').write_text(readme, encoding='utf-8')
    run([sys.executable, HERE / 'third_party_notices.py', '--pyinstaller',
         '--output', folder / 'THIRD-PARTY-NOTICES.txt'])

    if not args.skip_test:
        run([sys.executable, HERE / 'smoke_test.py', '--expect-version', version, program])

    archive = shutil.make_archive(
        str(output / f'{NAME}-{version}-{system}-{machine}'),
        'zip' if system == 'windows' else 'gztar',
        root_dir=output, base_dir=NAME,
    )
    archive = Path(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    Path(str(archive) + '.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')

    megabyte = 1024 * 1024
    print(f'\n{folder}: {folder_size(folder) / megabyte:.0f} MB')
    print(f'{archive}: {archive.stat().st_size / megabyte:.0f} MB, sha256 {digest}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
