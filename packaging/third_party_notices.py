#!/usr/bin/env python3
"""Write the licence notices of a packaged ProSiT.

The executables and the Docker image contain, besides the tool, Python and
every package the tool depends on. This writes what whoever receives them is
entitled to know: for each package its name, version, licence, where its
source is, and the licence texts it ships. Before that list comes
THIRD-PARTY-LICENSES, which covers what the tool's own source tree includes.

Run it with the Python of the environment that is being packaged:

    python packaging/third_party_notices.py > THIRD-PARTY-NOTICES.txt
    python packaging/third_party_notices.py --pyinstaller --output THIRD-PARTY-NOTICES.txt
"""

import argparse
import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = 'prosit-tool'
SOURCE = 'https://github.com/franvinci/prosit-tool'
RULE = '=' * 78

# Files of a distribution that state its licence or name its authors.
NOTICE_FILE = re.compile(r'^(LICEN[CS]E|COPYING|COPYRIGHT|NOTICE|AUTHORS)', re.IGNORECASE)
UNDECLARED = 'see its licence text below'
# GPL and AGPL, but not LGPL: in the licence a package declares...
COPYLEFT = re.compile(r'(?<![A-Za-z])A?GPL|GNU (Affero )?General Public', re.IGNORECASE)
# ...and, for a package that declares none, at the top of its licence text.
# (Not just "GPL": other licences say of themselves that they are "GPL compatible".)
COPYLEFT_TEXT = re.compile(r'under\s+the\s+terms\s+of\s+the\s+GNU\s+(Affero\s+)?General\s+Public\s+License',
                           re.IGNORECASE)


def canonical(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def requirement_parser():
    """``packaging``'s Requirement, wherever this environment has it; ``None`` if nowhere."""
    for module in ('packaging.requirements', 'pip._vendor.packaging.requirements'):
        try:
            return __import__(module, fromlist=['Requirement']).Requirement
        except ImportError:
            continue
    return None


def needed_distributions():
    """The installed distributions that ``prosit-tool`` needs, itself included.

    Without a way to read the requirements (no ``packaging``), every installed
    distribution is listed: more than what is needed, never less.
    """
    installed = {}
    for distribution in metadata.distributions():
        name = distribution.metadata['Name']
        if name:
            installed.setdefault(canonical(name), distribution)
    if ROOT not in installed:
        sys.exit(f'{ROOT} is not installed in this environment ({sys.prefix})')

    Requirement = requirement_parser()
    if Requirement is None:
        return dict(sorted(installed.items()))

    needed, waiting = {}, [ROOT]
    while waiting:
        name = canonical(waiting.pop())
        if name in needed or name not in installed:
            continue
        needed[name] = installed[name]
        for line in installed[name].requires or []:
            requirement = Requirement(line)
            if requirement.marker is None or requirement.marker.evaluate({'extra': ''}):
                waiting.append(requirement.name)
    return dict(sorted(needed.items()))


def licence_of(distribution):
    """The licence as the distribution declares it, in one line."""
    declared = distribution.metadata
    if declared.get('License-Expression'):
        return declared['License-Expression']
    named = [line.split('::')[-1].strip() for line in declared.get_all('Classifier') or []
             if line.startswith('License ::')]
    named = [name for name in named if name != 'OSI Approved']
    if named:
        return '; '.join(named)
    stated = (declared.get('License') or '').strip()
    if stated and '\n' not in stated and len(stated) <= 80:
        return stated
    return UNDECLARED


def is_copyleft(distribution):
    declared = licence_of(distribution)
    if declared != UNDECLARED:
        return bool(COPYLEFT.search(declared))
    return any(COPYLEFT_TEXT.search(text[:3000]) for _, text in notice_files(distribution))


def copyleft_licence(distribution):
    """The licence of a distribution that ``is_copyleft``, in words."""
    declared = licence_of(distribution)
    return 'GNU General Public License, see its text' if declared == UNDECLARED else declared


def home_of(distribution):
    declared = distribution.metadata
    links = {}
    for line in declared.get_all('Project-URL') or []:
        label, _, address = line.partition(',')
        links[label.strip().lower()] = address.strip()
    for label in ('source', 'source code', 'repository', 'homepage', 'home'):
        if links.get(label):
            return links[label]
    return declared.get('Home-page') or next(iter(links.values()), '')


def notice_files(distribution):
    """``(name, text)`` of the licence files the distribution ships."""
    found = []
    for entry in distribution.files or []:
        parts = entry.parts
        inside = [index for index, part in enumerate(parts) if part.endswith('.dist-info')]
        if not inside:
            continue
        below = parts[inside[0] + 1:]
        if not below or not (below[0] == 'licenses' or NOTICE_FILE.match(below[-1])):
            continue
        path = Path(entry.locate())
        if path.is_file():
            found.append(('/'.join(below), path.read_text(encoding='utf-8', errors='replace').strip()))
    return sorted(found)


def source_tree_notices(tool):
    """THIRD-PARTY-LICENSES as installed with the tool, or as found next to this script."""
    for name, text in notice_files(tool):
        if name.endswith('THIRD-PARTY-LICENSES'):
            return text
    beside = Path(__file__).resolve().parent.parent / 'THIRD-PARTY-LICENSES'
    return beside.read_text(encoding='utf-8').strip() if beside.is_file() else ''


def python_licence():
    for candidate in (Path(sys.base_prefix) / 'LICENSE.txt',
                      Path(sys.base_prefix) / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'LICENSE.txt'):
        if candidate.is_file():
            return candidate.read_text(encoding='utf-8', errors='replace').strip()
    return ''


def write_notices(out, with_pyinstaller=False):
    distributions = needed_distributions()
    tool = distributions.pop(ROOT)
    version = tool.version
    copyleft = [distribution for distribution in distributions.values() if is_copyleft(distribution)]

    def line(text=''):
        out.write(text + '\n')

    line(f'ProSiT Tool {version} - third-party notices')
    line(RULE)
    line()
    line('This package contains ProSiT Tool (MIT License, see LICENSE), the Python')
    line(f'runtime and the {len(distributions)} Python packages it needs. This file says what each')
    line('of them is, under which licence it comes, and where its source code is.')
    line()
    if copyleft:
        line('Packages under the GNU General Public License or the GNU Affero General')
        line('Public License are among them:')
        line()
        for distribution in copyleft:
            line(f'  - {distribution.metadata["Name"]} {distribution.version} ({copyleft_licence(distribution)})')
        line()
        line('This package as a whole is therefore distributed under the terms of the')
        line('GNU Affero General Public License, version 3 or (at your option) any later')
        line('version: you may use it, study it, share it and change it under those terms,')
        line('and it comes with NO WARRANTY, to the extent permitted by law. The parts')
        line('written for ProSiT Tool remain available under the MIT License as well.')
        line()
        line('The complete corresponding source code is public:')
        line()
        line(f'  - ProSiT Tool {version}, with the scripts this package was built with')
        line(f'    (the "packaging" folder): {SOURCE}/tree/v{version}')
        line('  - every Python package, at the version listed below:')
        line('    https://pypi.org/project/<name>/<version>/#files ("Source Distribution")')
        line()
    line(RULE)
    line('PART 1 - What the source code of ProSiT Tool includes')
    line(RULE)
    line()
    line(source_tree_notices(tool) or f'See THIRD-PARTY-LICENSES at {SOURCE}')
    line()
    line(RULE)
    line('PART 2 - The Python runtime')
    line(RULE)
    line()
    line(f'Python {sys.version.split()[0]} (https://www.python.org), Python Software Foundation License')
    line('Version 2. It incorporates software by other authors (OpenSSL, SQLite, zlib,')
    line('bzip2, XZ Utils, libffi and more), listed with their licences at')
    line('https://docs.python.org/3/license.html')
    if with_pyinstaller:
        line()
        line('The executable is started by the bootloader of PyInstaller')
        line('(https://pyinstaller.org): GPL-2.0-or-later, with an exception that allows')
        line('distributing the programs it packages under their own licences.')
    licence = python_licence()
    if licence:
        line()
        line(licence)
    line()
    line(RULE)
    line(f'PART 3 - The Python packages ({len(distributions)})')
    line(RULE)
    for distribution in distributions.values():
        name = distribution.metadata['Name']
        line()
        line('-' * 78)
        line(f'{name} {distribution.version}')
        line(f'Licence: {licence_of(distribution)}')
        home = home_of(distribution)
        if home:
            line(f'Home:    {home}')
        line(f'Source:  https://pypi.org/project/{canonical(name)}/{distribution.version}/#files')
        line('-' * 78)
        texts = notice_files(distribution)
        if not texts:
            line()
            line('(this package ships no licence file: see its home page)')
        for title, text in texts:
            line()
            if len(texts) > 1:
                line(f'[{title}]')
                line()
            line(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--output', '-o', help='file to write (default: standard output)')
    parser.add_argument('--pyinstaller', action='store_true',
                        help='the package is an executable built with PyInstaller')
    args = parser.parse_args(argv)
    if args.output:
        with open(args.output, 'w', encoding='utf-8', newline='\n') as out:
            write_notices(out, args.pyinstaller)
    else:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        write_notices(sys.stdout, args.pyinstaller)
    return 0


if __name__ == '__main__':
    sys.exit(main())
