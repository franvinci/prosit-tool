#!/usr/bin/env python3
"""Fetch the source code of the copyleft packages a packaged ProSiT contains.

The executables and the Docker image include packages under the GNU General
Public License or the GNU Affero General Public License (pm4py, CVXOPT).
Whoever hands them out has to offer the source of those packages from the same
place. This downloads from PyPI the source distribution of each of them, at
the version installed in the environment it is run with, and checks every file
against the SHA-256 that PyPI publishes for it.

    python packaging/copyleft_sources.py --output copyleft-sources
"""

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from third_party_notices import SOURCE, canonical, copyleft_licence, is_copyleft, needed_distributions  # noqa: E402


def fetch(address):
    with urllib.request.urlopen(address, timeout=120) as response:
        return response.read()


def source_distribution(name, version):
    """``(file name, bytes)`` of the source distribution of a release on PyPI."""
    release = json.loads(fetch(f'https://pypi.org/pypi/{canonical(name)}/{version}/json'))
    for entry in release['urls']:
        if entry['packagetype'] == 'sdist':
            content = fetch(entry['url'])
            if hashlib.sha256(content).hexdigest() != entry['digests']['sha256']:
                sys.exit(f'{entry["filename"]} does not match the SHA-256 published by PyPI')
            return entry['filename'], content
    sys.exit(f'{name} {version} has no source distribution on PyPI')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--output', type=Path, required=True, help='folder to write the sources to')
    args = parser.parse_args(argv)

    distributions = needed_distributions()
    tool = distributions.pop('prosit-tool')
    copyleft = [distribution for distribution in distributions.values() if is_copyleft(distribution)]

    args.output.mkdir(parents=True, exist_ok=True)
    lines = [
        'Source code of the packages under the GNU General Public License or the',
        'GNU Affero General Public License that the executables and the Docker',
        f'image of ProSiT Tool {tool.version} contain, as published on https://pypi.org:',
        '',
    ]
    for distribution in copyleft:
        name, version = distribution.metadata['Name'], distribution.version
        filename, content = source_distribution(name, version)
        (args.output / filename).write_bytes(content)
        lines.append(f'  {filename}  ({name} {version}: {copyleft_licence(distribution)})')
        print(f'{filename}: {len(content)} bytes')
    lines += [
        '',
        'The source code of ProSiT Tool itself, with the scripts those packages',
        'are built with (the "packaging" folder), is at',
        f'{SOURCE}/tree/v{tool.version}',
        '',
        'THIRD-PARTY-NOTICES.txt, inside each executable and image, lists every',
        'other component with its licence and says where its source is.',
    ]
    (args.output / 'README.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
