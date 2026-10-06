#!/usr/bin/env bash
set -euo pipefail

HERE="$(dirname "$(readlink -f "${0}")")"
PROJECT_ROOT="$(dirname "$HERE")"
BUILD_DIR="${PROJECT_ROOT}/build/appimage"
APPDIR="${BUILD_DIR}/AppDir"

echo "=== Building Parakeet Cage AppImage ==="

rm -rf "${BUILD_DIR}"
mkdir -p "${APPDIR}/usr/bin" "${APPDIR}/usr/share/icons/hicolor/256x256/apps" "${APPDIR}/usr/lib/python"

# Copy package and entrypoint
cp -r "${PROJECT_ROOT}/parakeet_cage" "${APPDIR}/usr/lib/python/"
cp "${PROJECT_ROOT}/packaging/parakeet-cage.desktop" "${APPDIR}/"

# AppRun script
cat << 'EOF' > "${APPDIR}/AppRun"
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
export PYTHONPATH="${HERE}/usr/lib/python:${PYTHONPATH:-}"
export PATH="${HERE}/usr/bin:${PATH:-}"
exec python3 -m parakeet_cage.app "$@"
EOF
chmod +x "${APPDIR}/AppRun"

# Generate AppImage icon
python3 -c "
from PIL import Image, ImageDraw
img = Image.new('RGBA', (256, 256), color=(0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.ellipse([16, 16, 240, 240], fill='#2ecc71', outline='#27ae60', width=8)
img.save('${APPDIR}/parakeet-cage.png')
"
cp "${APPDIR}/parakeet-cage.png" "${APPDIR}/.DirIcon"

echo "AppDir populated successfully at ${APPDIR}."
