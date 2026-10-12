#!/bin/sh
# Builds libsm64 and copies the shared library next to this script.
# Requirements: git, make, gcc/clang, python3 (used by libsm64's build to extract data).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/libsm64-src"

if [ ! -d "$SRC" ]; then
    git clone --depth 1 https://github.com/libsm64/libsm64.git "$SRC"
fi

cd "$SRC"
make -j"$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)" lib

case "$(uname -s)" in
    Darwin) cp dist/libsm64.dylib "$HERE/" ;;
    MINGW*|MSYS*|CYGWIN*) cp dist/sm64.dll "$HERE/" ;;
    *) cp dist/libsm64.so "$HERE/" ;;
esac

echo "libsm64 built. Now copy your Super Mario 64 (US) ROM to $HERE/sm64.z64"
