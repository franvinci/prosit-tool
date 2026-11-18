# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller recipe of the ProSiT executable.
#
# The result is a folder, prosit-tool, with the program (prosit-tool, or
# prosit-tool.exe on Windows) and everything it needs: nothing has to be
# installed to run it. Use packaging/build_executable.py, which also adds the
# licence notices, tries the result and packs it. To run only this step, in an
# environment where the tool and PyInstaller are installed:
#
#     pyinstaller --noconfirm packaging/prosit-tool.spec

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# What reading the imports does not show.
hidden_imports = (
    # pm4py and prosit-pm choose algorithms and their variants by name.
    collect_submodules('pm4py')
    + collect_submodules('prosit')
    # river is compiled: its modules import one another where no one can see.
    + collect_submodules('river')
)

datas = (
    # The page: templates, scripts, styles and the libraries it draws with.
    collect_data_files('prosit_tool')
    + collect_data_files('pm4py')
)

# Installed because pm4py asks for them, never used by the tool: it draws
# nothing on the server (the charts and the diagrams are drawn by the browser).
# The whole test suite passes in an environment without them.
never_used = ['matplotlib', 'mpl_toolkits', 'PIL', 'fontTools', 'kiwisolver', 'contourpy', 'cycler']

analysis = Analysis(
    [os.path.join(SPECPATH, 'launcher.py')],
    datas=datas,
    hiddenimports=hidden_imports,
    excludes=never_used + ['tkinter', '_tkinter', 'IPython', 'pytest', '_pytest'],
)

executable = EXE(
    PYZ(analysis.pure),
    analysis.scripts,
    exclude_binaries=True,
    name='prosit-tool',
    # A window with the address of the tool and how to stop it: closing it
    # stops the program.
    console=True,
    # Compressed executables are what antivirus programs distrust most.
    upx=False,
)

COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    upx=False,
    name='prosit-tool',
)
