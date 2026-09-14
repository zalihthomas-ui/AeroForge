#!/usr/bin/env bash
# Rebuilds the vendored XFOIL wheel (vendor/xfoil/) from source on Windows.
#
# Background: `pip install xfoil` fails everywhere because the PyPI sdist
# for xfoil 1.1.1 is missing CMakeLists.txt and src/ (a packaging bug
# upstream). This script builds directly from the GitHub source instead.
# See docs/architecture/roadmap.md's v0.4 section for the full debugging
# history and vendor/xfoil/README.md for why the wheel is vendored.
#
# Requires MSYS2 (https://www.msys2.org/) with MinGW64 gcc/gfortran and
# CMake+mingw32-make. Run this from Git Bash with those tools reachable
# via the paths below (adjust MSYS2_ROOT if installed elsewhere).
#
# Usage: ./scripts/build_xfoil_windows.sh [/path/to/python.exe]

set -euo pipefail

MSYS2_ROOT="${MSYS2_ROOT:-/c/msys64}"
PYTHON="${1:-python}"
WORKDIR="$(mktemp -d)"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== Checking MinGW64 toolchain =="
for tool in gcc.exe g++.exe gfortran.exe mingw32-make.exe; do
    if [ ! -f "$MSYS2_ROOT/mingw64/bin/$tool" ]; then
        echo "Missing $MSYS2_ROOT/mingw64/bin/$tool" >&2
        if [ "$tool" = "mingw32-make.exe" ]; then
            echo "Install it with: $MSYS2_ROOT/usr/bin/pacman.exe -S mingw-w64-x86_64-make" >&2
        else
            echo "Install MSYS2 MinGW64 gcc-fortran: $MSYS2_ROOT/usr/bin/pacman.exe -S mingw-w64-x86_64-gcc-fortran" >&2
        fi
        exit 1
    fi
done

"$PYTHON" -m pip install --quiet cmake scikit-build setuptools wheel

echo "== Cloning xfoil-python source (PyPI sdist is broken, must build from git) =="
git clone --quiet https://github.com/DARcorporation/xfoil-python.git "$WORKDIR/xfoil-python"
cd "$WORKDIR/xfoil-python"

# Pin the mingw32 compiler: setuptools' build_ext defaults to 'msvc' on
# Windows regardless of whether MSVC is actually installed, which makes
# CMake try to use a Visual Studio generator that doesn't exist here.
cat > setup.cfg << 'EOF'
[build_ext]
compiler=mingw32
EOF

export PATH="$MSYS2_ROOT/mingw64/bin:$PATH"

echo "== Building statically-linked wheel =="
# -static avoids depending on libgfortran/libgcc/libwinpthread MinGW
# runtime DLLs at import time (ctypes on Windows/Python 3.8+ doesn't
# consult PATH for a loaded DLL's own dependencies unless the caller
# explicitly uses os.add_dll_directory, so an unlinked wheel would fail to
# import unless every consumer remembered to do that).
"$PYTHON" setup.py bdist_wheel "-DCMAKE_SHARED_LINKER_FLAGS=-static"

WHEEL="$(ls dist/xfoil-*.whl | head -1)"
mkdir -p "$REPO_ROOT/vendor/xfoil"
cp "$WHEEL" "$REPO_ROOT/vendor/xfoil/"
echo "== Done: $(basename "$WHEEL") copied to vendor/xfoil/ =="

rm -rf "$WORKDIR"
