#!/usr/bin/env bash
# Installs CalculiX (ccx.exe) via MSYS2's package manager.
#
# Unlike XFOIL, CalculiX is NOT vendored in this repo: ccx.exe depends on a
# large stack of MSYS2 runtime DLLs (libopenblas, libarpack, libpastix,
# libscotch, ...) that would be impractical to statically link or bundle.
# Instead, agents/structures/agent.py locates ccx.exe at runtime (checking
# PATH, then the default MSYS2 install location) and requires it to be
# installed separately -- this script automates that.
#
# IMPORTANT: see docs/architecture/roadmap.md's v0.5 section. The default
# solver this MSYS2 build resolves to (PaStiX) hangs indefinitely even on
# trivial problems -- agents/structures/agent.py always forces
# `*STATIC, SOLVER=SPOOLES` in generated input decks to avoid this. If you
# hand-write a .inp file for testing, do the same or ccx.exe will hang
# forever with no error message.
#
# Requires MSYS2 (https://www.msys2.org/). Run from Git Bash.
# Usage: ./scripts/install_calculix_windows.sh

set -euo pipefail

MSYS2_ROOT="${MSYS2_ROOT:-/c/msys64}"
PACMAN="$MSYS2_ROOT/usr/bin/pacman.exe"

if [ ! -f "$PACMAN" ]; then
    echo "MSYS2 not found at $MSYS2_ROOT. Install it from https://www.msys2.org/ first." >&2
    exit 1
fi

echo "== Refreshing MSYS2 package databases =="
"$PACMAN" -Syy --noconfirm

echo "== Installing CalculiX (this pulls in a large sparse-linear-algebra"
echo "   dependency chain: openblas, arpack, scotch, pastix, hdf5, ... -- "
echo "   expect this to take a while and download a few hundred MB) =="
"$PACMAN" -S --noconfirm mingw-w64-x86_64-calculix-ccx

CCX="$MSYS2_ROOT/mingw64/bin/ccx.exe"
if [ ! -f "$CCX" ]; then
    echo "Install appeared to succeed but $CCX is missing." >&2
    exit 1
fi

echo "== Verifying ccx.exe runs =="
"$CCX" -v

echo "== Done. ccx.exe is at $CCX =="
echo "agents/structures/agent.py looks for it on PATH or at this default"
echo "location automatically -- no further setup needed."
