ProSiT Tool {version}
====================================================================

Unpack the whole archive before starting: the program needs the folder
"_internal" that is next to it.

START
    Windows   double-click prosit-tool.exe
    macOS     double-click prosit-tool   (the first time, see below)
    Linux     ./prosit-tool

  A window with some text opens: that is the program. A few seconds later your
  browser shows the tool, at http://localhost:5050. Everything stays on your
  computer: the page is served by the program in that window.

STOP
    Close that window, or press Ctrl+C in it.

YOUR DATA
  Uploaded logs, simulations and the list of sessions are kept in

    Windows   %LOCALAPPDATA%\prosit-tool
    macOS     ~/Library/Application Support/prosit-tool
    Linux     ~/.local/share/prosit-tool

  They stay there when this folder is replaced by a newer version.
  "prosit-tool --help" lists the options (another folder, another port).

THE FIRST START ON WINDOWS
  The program is not signed, so "Windows protected your PC" may appear:
  choose "More info", then "Run anyway".

THE FIRST START ON MACOS
  The program is not signed, and macOS refuses to open what it has just
  downloaded and does not know. Once, in the Terminal:

    xattr -dr com.apple.quarantine /path/to/this/folder

  then double-click prosit-tool.

LICENCES
  ProSiT Tool is released under the MIT License (see LICENSE). This package
  also contains Python and the libraries that the tool needs, each under its
  own licence. Some of them are under the GNU General Public License or the
  GNU Affero General Public License, so the package as a whole is distributed
  under the GNU Affero General Public License, version 3 or later.
  THIRD-PARTY-NOTICES.txt lists every component and says where its source
  code is.

  https://github.com/franvinci/prosit-tool
