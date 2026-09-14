# Vendored XFOIL wheel

`xfoil-1.1.1-cp313-cp313-win_amd64.whl` is a self-contained build of
[DARcorporation/xfoil-python](https://github.com/DARcorporation/xfoil-python)
(real XFOIL, compiled from its actual Fortran source — not a surrogate).
It's vendored here, rather than installed from PyPI, because **the PyPI
sdist for `xfoil` 1.1.1 is broken**: it's missing `CMakeLists.txt` and the
entire `src/` Fortran source tree (a packaging bug upstream — compare the
sdist to the GitHub repo and the files are simply absent), so
`pip install xfoil` fails on every platform, not just this one.

Statically linked (`-DCMAKE_SHARED_LINKER_FLAGS=-static`) so the resulting
`libxfoil.dll` depends only on `KERNEL32.dll`/`msvcrt.dll` — no MinGW
runtime DLLs need to be on `PATH` at import time.

Install it directly:

```bash
pip install vendor/xfoil/xfoil-1.1.1-cp313-cp313-win_amd64.whl
```

**Platform-specific**: this wheel only works on Windows x64 with CPython
3.13 (matches this project's dev environment). It is not a substitute for
a real cross-platform dependency — `agents/aerodynamics/agent.py` treats
`xfoil` as optional (feature-detected at import time) and falls back to
the NeuralFoil surrogate everywhere it isn't installed, including CI
(`ubuntu-latest`, see `.github/workflows/ci.yml`).

## Known cosmetic issue

`XFoil.__del__` (upstream, in the `xfoil` package itself) fails on 64-bit
Python with `ctypes.ArgumentError: argument 1: OverflowError: int too long
to convert` when freeing the loaded DLL handle, followed by a
`PermissionError` trying to delete the temp DLL copy. Python reports this
as an ignored exception / `PytestUnraisableExceptionWarning` — it does not
fail tests or affect returned results (they're already computed before
cleanup runs), it just leaves temp `.dll` files under `%TEMP%` and prints a
traceback. Not patched here since it's upstream, third-party code we don't
control the install of long-term.

## Rebuilding for a different platform/Python version

Run `scripts/build_xfoil_windows.sh` (Windows + MSYS2/MinGW64 only) or, on
Linux/macOS, XFOIL's own CMake build generally works without the
Windows-specific packaging issues documented here — see
`docs/architecture/roadmap.md`'s v0.4 section for the full debugging
history (missing `mingw32-make`, the broken sdist, distutils defaulting to
the `msvc` compiler class instead of `mingw32`, and why static linking was
needed) before troubleshooting a build failure on a new machine.
