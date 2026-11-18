"""What turns the repository into something people install: Docker, scripts, executable, notices."""

import os
import re
import socket
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PACKAGING = REPO / 'packaging'
INSTALLER = REPO / 'installer'
WORKFLOWS = REPO / '.github' / 'workflows'

SHELL_SCRIPTS = sorted(INSTALLER.glob('*/*.sh'))
BATCH_SCRIPTS = sorted(INSTALLER.glob('*/*.bat'))


def text_of(path):
    return Path(path).read_bytes().decode('utf-8')


def lines_of(path):
    """Lines that say something: no blank ones, no comments."""
    return [line.strip() for line in text_of(path).splitlines() if line.strip() and not line.strip().startswith('#')]


def project_table():
    """``[project]`` of pyproject.toml (Python 3.10 has no TOML reader of its own)."""
    try:
        import tomllib
    except ImportError:
        tomllib = pytest.importorskip('tomli')
    return tomllib.loads(text_of(REPO / 'pyproject.toml'))['project']


def requirement_name(requirement):
    return re.split(r'[\s<>=!~;\[]', requirement.strip(), maxsplit=1)[0].lower().replace('_', '-')


# --- the Docker image -------------------------------------------------------------------

def test_the_image_is_built_with_pip_alone():
    dockerfile = '\n'.join(lines_of(REPO / 'Dockerfile'))      # the instructions, not the comments

    for unwanted in ('conda', 'graphviz', 'apt-get', 'gcc'):
        assert unwanted not in dockerfile.lower(), unwanted
    assert '-c packaging/constraints.txt' in dockerfile          # the tested versions
    assert 'CMD ["prosit-tool"]' in dockerfile
    assert 'PROSIT_TOOL_DATA_DIR=/data' in dockerfile
    assert 'PROSIT_TOOL_HOST=0.0.0.0' in dockerfile and 'PROSIT_TOOL_NO_BROWSER=1' in dockerfile
    assert '/api/health' in dockerfile                            # the health check
    assert 'TARGETARCH' not in dockerfile                         # set only by the newer builder


def test_only_what_the_image_is_built_from_is_sent_to_docker():
    rules = lines_of(REPO / '.dockerignore')

    assert rules[0] == '*', 'everything is left out unless listed'
    allowed = [rule[1:].rstrip('/') for rule in rules if rule.startswith('!')]
    for private in ('uploads', 'simulations', 'instance', 'example_data', 'tests', '.git', '.claude'):
        assert not any(entry == private or entry.startswith(private + '/') for entry in allowed), private

    # ...and everything the Dockerfile copies is among it
    copied = []
    for line in lines_of(REPO / 'Dockerfile'):
        if line.startswith('COPY ') and '--from=' not in line:
            copied += line.split()[1:-1]
    assert copied
    for source in copied:
        assert any(source == entry or source.startswith(entry + '/') for entry in allowed), source
        assert (REPO / source).exists(), source


def test_compose_keeps_the_tool_on_this_computer_and_the_data_in_the_folder():
    compose = text_of(REPO / 'docker-compose.yml')

    assert re.search(r'^\s*image: ghcr\.io/franvinci/prosit-tool:latest\s*$', compose, re.M)
    assert re.search(r'^\s*build: \.\s*$', compose, re.M)          # from a checkout, without the registry
    ports = re.findall(r'^\s*-\s*"([^"]*5050[^"]*)"\s*$', compose, re.M)
    assert ports == ['127.0.0.1:5050:5050']
    volumes = re.findall(r'^\s*-\s*(\./\S+)\s*$', compose, re.M)
    assert volumes == ['./uploads:/data/uploads', './simulations:/data/simulations', './instance:/data/instance']


@pytest.mark.parametrize('name', ['Dockerfile', 'docker-compose.yml', '.dockerignore'])
def test_docker_files_keep_their_line_endings(name):
    content = (REPO / name).read_bytes()

    assert content.count(b'\r\n') == content.count(b'\n') > 0


# --- the helper scripts ------------------------------------------------------------------------

def test_there_are_scripts_for_the_three_systems():
    assert [path.relative_to(INSTALLER).as_posix() for path in SHELL_SCRIPTS] == [
        'macos/run-docker.sh', 'macos/setup-macos.sh', 'macos/stop-docker.sh',
        'ubuntu/run-docker.sh', 'ubuntu/setup-ubuntu.sh', 'ubuntu/stop-docker.sh',
    ]
    assert [path.relative_to(INSTALLER).as_posix() for path in BATCH_SCRIPTS] == [
        'windows/run-docker.bat', 'windows/setup-windows.bat', 'windows/stop-docker.bat',
    ]


@pytest.mark.parametrize('script', SHELL_SCRIPTS, ids=lambda path: path.parent.name + '/' + path.name)
def test_shell_script_can_be_run(script):
    content = script.read_bytes()

    assert content.startswith(b'#!/bin/bash\n')
    assert b'\r' not in content, 'a carriage return breaks the first line of a shell script'
    if os.name != 'nt':
        assert os.access(script, os.X_OK), 'not executable'
        assert subprocess.run(['bash', '-n', str(script)], capture_output=True).returncode == 0


@pytest.mark.parametrize('script', BATCH_SCRIPTS, ids=lambda path: path.name)
def test_batch_script_is_what_cmd_expects(script):
    content = script.read_bytes()

    assert content.count(b'\r\n') == content.count(b'\n') > 0
    content.decode('ascii')                      # cmd.exe garbles anything else
    text = content.decode('ascii')
    # %errorlevel% inside a parenthesised block holds the value from before the
    # block: the checks are written "if errorlevel 1", outside any block.
    assert '%errorlevel%' not in text.lower()
    assert text.count('(') == text.count(')')
    for label in re.findall(r'goto (\w+)', text):
        assert f'\r\n:{label}\r\n' in text, label


@pytest.mark.parametrize('script', SHELL_SCRIPTS + BATCH_SCRIPTS, ids=lambda path: path.parent.name + '/' + path.name)
def test_scripts_use_the_compose_that_comes_with_docker(script):
    commands = [line for line in lines_of(script) if not line.upper().startswith('REM ')]

    for line in commands:
        assert not re.search(r'docker-compose\s+(up|down|ps|logs|restart|--version)', line), line
    if 'setup' not in script.name:
        assert any(re.search(r'docker compose (up|down)\b', line) for line in commands)
        assert any('../..' in line or '..\\..' in line for line in commands), 'runs from the folder of the project'


# --- the versions a release is built from ------------------------------------------------------------

def test_every_dependency_has_a_tested_version():
    pinned = {}
    for line in lines_of(PACKAGING / 'constraints.txt'):
        requirement = line.split(';')[0].strip()
        assert re.fullmatch(r'[A-Za-z0-9._-]+==[A-Za-z0-9._+!-]+', requirement), line
        name, version = requirement.split('==')
        pinned.setdefault(name.lower(), set()).add(version)

    project = project_table()
    for requirement in project['dependencies'] + project['optional-dependencies']['dev']:
        assert requirement_name(requirement) in pinned, requirement
    # the simulation engine is one exact version, the same in both files
    assert 'prosit-pm==1.0.5' in project['dependencies']
    assert pinned['prosit-pm'] == {'1.0.5'}


def test_the_executable_is_built_with_one_version_of_pyinstaller():
    requirements = lines_of(PACKAGING / 'requirements-build.txt')

    assert any(re.fullmatch(r'pyinstaller==[\d.]+', line) for line in requirements)
    assert all('==' in line for line in requirements)


# --- the executable -----------------------------------------------------------------------------------

def test_what_the_executable_leaves_out_is_not_used_by_the_tool():
    spec = text_of(PACKAGING / 'prosit-tool.spec')
    left_out = re.search(r'never_used = \[([^\]]+)\]', spec)
    assert left_out, 'the recipe names what it leaves out'
    names = re.findall(r"'([^']+)'", left_out.group(1))
    assert 'matplotlib' in names

    for source in (REPO / 'prosit_tool').rglob('*.py'):
        code = source.read_text(encoding='utf-8')
        for name in names:
            assert not re.search(rf'^\s*(import|from)\s+{re.escape(name)}\b', code, re.M), (source.name, name)


def test_the_note_that_goes_with_the_executable_is_filled_in_by_the_build():
    note = text_of(PACKAGING / 'README-executable.txt')

    assert '{version}' in note
    assert 'THIRD-PARTY-NOTICES.txt' in note and 'LICENSE' in note
    note.encode('ascii')                         # read in Notepad as well as in a terminal
    build = text_of(PACKAGING / 'build_executable.py')
    for name in ('README-executable.txt', 'prosit-tool.spec', 'smoke_test.py', 'third_party_notices.py'):
        assert name in build and (PACKAGING / name).is_file()


class TestWindowOfTheExecutable:
    """Started with a double click on Windows, the program owns a window that closes with it."""

    @pytest.fixture
    def launcher(self, monkeypatch):
        from prosit_tool import cli

        asked = []
        monkeypatch.setattr('builtins.input', lambda prompt='': asked.append(prompt) or '')

        def launch(outcome, own_window):
            def _launch(argv=None):
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
            monkeypatch.setattr(cli, '_launch', _launch)
            monkeypatch.setattr(cli, '_window_closes_with_the_program', lambda: own_window)
            return cli.main([])
        return launch, asked

    def test_an_error_stays_on_screen_until_it_is_read(self, launcher):
        launch, asked = launcher

        assert launch(2, own_window=True) == 2
        assert len(asked) == 1 and 'close this window' in asked[0]

    def test_a_crash_is_shown_and_stays_on_screen(self, launcher, capsys):
        launch, asked = launcher

        assert launch(RuntimeError('the data folder cannot be written'), own_window=True) == 1
        assert 'the data folder cannot be written' in capsys.readouterr().err
        assert len(asked) == 1

    def test_a_normal_end_closes_the_window(self, launcher):
        launch, asked = launcher

        assert launch(0, own_window=True) == 0
        assert asked == []

    def test_in_a_terminal_nothing_waits_and_errors_are_raised_as_usual(self, launcher):
        launch, asked = launcher

        assert launch(2, own_window=False) == 2
        with pytest.raises(RuntimeError):
            launch(RuntimeError('boom'), own_window=False)
        assert asked == []

    def test_only_the_windows_executable_owns_its_window(self):
        from prosit_tool import cli

        # these tests run from source: never a frozen executable
        assert cli._window_closes_with_the_program() is False


# --- licences ---------------------------------------------------------------------------------------------

def test_the_libraries_of_the_page_are_named_with_their_licences():
    """Every library in static/vendor, at the version that is there."""
    notices = text_of(REPO / 'THIRD-PARTY-LICENSES')
    table = text_of(REPO / 'prosit_tool' / 'static' / 'vendor' / 'README.md')
    libraries = re.findall(r'^\| `[^`]+` \| (\S+) ([\d.]+)', table, re.M)
    assert len(libraries) == 6

    for name, version in libraries:
        shown = {'bootstrap': 'Bootstrap', 'chart.js': 'Chart.js', 'feather-icons': 'Feather',
                 '@viz-js/viz': 'Viz.js'}.get(name, name)
        assert f'{shown} {version}' in notices, (name, version)
    for expected in ('Permission is hereby granted, free of charge', 'Eclipse Public License - v 2.0',
                     'Graphviz 16.1.0', 'https://gitlab.com/graphviz/graphviz', 'Expat maintainers',
                     'GNU Affero General Public License', 'pm4py'):
        assert expected in notices, expected
    assert 'Eclipse Public License 2.0' in ' '.join(table.split())


def test_the_notices_travel_with_the_pip_package():
    files = project_table()['license-files']

    assert files == ['LICENSE', 'THIRD-PARTY-LICENSES']
    assert all((REPO / name).is_file() for name in files)


def run_script(name, *arguments, timeout=300):
    return subprocess.run([sys.executable, str(PACKAGING / name), *arguments], cwd=REPO,
                          capture_output=True, text=True, encoding='utf-8', timeout=timeout)


def test_the_notices_of_a_packaged_copy_list_what_is_installed():
    try:
        metadata.version('prosit-tool')
    except metadata.PackageNotFoundError:
        pytest.skip('the tool is not installed in this environment')

    result = run_script('third_party_notices.py', '--pyinstaller')

    assert result.returncode == 0, result.stderr
    notices = result.stdout
    assert f'ProSiT Tool {metadata.version("prosit-tool")} - third-party notices' in notices
    # what makes the whole package AGPL is said at the top, with where the source is
    top = notices[:notices.index('PART 1')]
    assert re.search(r'^  - pm4py \S+ \(AGPL', top, re.M)
    assert re.search(r'^  - cvxopt \S+ \(GNU General Public License', top, re.M)
    assert 'GNU Affero General Public License, version 3' in top and 'github.com/franvinci/prosit-tool' in top
    assert not re.search(r'^  - (waitress|tqdm|prosit-pm) ', top, re.M)      # not copyleft
    for part in ('PART 1 - What the source code of ProSiT Tool includes', 'Graphviz 16.1.0',
                 'PART 2 - The Python runtime', 'bootloader of PyInstaller', 'PART 3 - The Python packages'):
        assert part in notices, part
    for package in ('pm4py', 'prosit-pm', 'Flask', 'numpy', 'waitress'):
        assert re.search(rf'^{re.escape(package)} \S+\nLicence: ', notices, re.M | re.I), package


# --- the workflows ------------------------------------------------------------------------------------------

def test_workflows_only_use_files_that_exist():
    workflows = sorted(WORKFLOWS.glob('*.yml'))
    assert [path.name for path in workflows] == ['release.yml', 'tests.yml']

    for workflow in workflows:
        content = text_of(workflow)
        assert '\t' not in content, 'YAML is indented with spaces'
        for path in set(re.findall(r'(?<![\w/.-])(packaging/[\w./-]+|\.github/workflows/[\w.-]+)', content)):
            assert (REPO / path).exists(), (workflow.name, path)


def test_a_release_is_built_on_a_python_the_tool_supports():
    release = text_of(WORKFLOWS / 'release.yml')
    version = re.search(r"PYTHON_VERSION: '(3\.\d+)'", release).group(1)

    assert f'Programming Language :: Python :: {version}' in project_table()['classifiers']
    assert f'ARG PYTHON_VERSION={version}' in text_of(REPO / 'Dockerfile')
    # every system an executable is promised for
    for runner in ('ubuntu-22.04', 'windows-2022', 'macos-15', 'macos-15-intel'):
        assert re.search(rf'^\s*os: {runner}\s*$', release, re.M), runner


# --- the test of what is released ------------------------------------------------------------------------------

def test_the_tool_goes_through_a_whole_session_when_started_as_a_program():
    """The same script tries the executable, the installed wheel and the Docker image."""
    result = run_script('smoke_test.py', sys.executable, '-m', 'prosit_tool')

    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Everything works' in result.stdout
    for step in ('it starts and listens', 'the page, its scripts', 'an event log is uploaded',
                 'the model and its parameters are discovered', 'its progress is reported',
                 'a simulation runs', 'the results are computed', 'the accuracy of the model is measured',
                 'downloaded as CSV and as XES', 'then deleted'):
        assert step in result.stdout, step


def test_the_smoke_test_says_what_does_not_work(tmp_path):
    not_prosit = tmp_path / 'not_prosit.py'
    not_prosit.write_text('import sys\nsys.exit(3)\n')

    result = run_script('smoke_test.py', '--startup-timeout', '20', sys.executable, str(not_prosit))

    assert result.returncode == 1
    assert 'FAILED: the program stopped at start-up with exit status 3' in result.stdout


def test_the_smoke_test_says_when_nothing_answers():
    with socket.socket() as probe:           # a port where nothing listens
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]

    result = run_script('smoke_test.py', '--url', f'http://127.0.0.1:{port}')

    assert result.returncode == 1
    assert 'FAILED:' in result.stdout and 'Traceback' not in result.stderr
