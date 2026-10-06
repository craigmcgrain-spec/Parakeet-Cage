#!/usr/bin/env bash
# Build the Parakeet Cage AppImage (see README.md -> AppImage packaging).
#
#   ./packaging/build_appimage.sh
#   PARAKEET_BUNDLE_MODEL=0 ./packaging/build_appimage.sh   # skip the 178 MB weights
#
# Environment:
#   PARAKEET_BUNDLE_MODEL  1 (default) bundle the model weights, 0 to omit them
#   PARAKEET_MODEL_DIR     weights directory (default: <repo>/models/parakeet-redux)
#   APPIMAGETOOL           appimagetool binary to use (default: appimagetool on PATH,
#                          downloaded into build/appimage when absent)
#
# The bundle is intentionally "thin": application code and model weights come from
# this repository, while python3, PyGObject, dbus-python and the pip dependencies
# are taken from the host - GTK/PyGObject extensions are compiled against the host
# interpreter and cannot be made portable by copying. AppRun preflights them.
set -euo pipefail

HERE="$(dirname "$(readlink -f "${0}")")"
PROJECT_ROOT="$(dirname "${HERE}")"
BUILD_DIR="${PROJECT_ROOT}/build/appimage"
APPDIR="${BUILD_DIR}/AppDir"
DIST_DIR="${PROJECT_ROOT}/dist"
BUNDLE_MODEL="${PARAKEET_BUNDLE_MODEL:-1}"
MODEL_SRC="${PARAKEET_MODEL_DIR:-${PROJECT_ROOT}/models/parakeet-redux}"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

log() { printf '==> %s\n' "$*"; }

VERSION="$(python3 -c "import sys; sys.path.insert(0, '${PROJECT_ROOT}'); import parakeet_cage; print(parakeet_cage.__version__)")"
OUT="${DIST_DIR}/Parakeet-Cage-${VERSION}-x86_64.AppImage"

log "Building Parakeet Cage ${VERSION}"
rm -rf "${BUILD_DIR}"
mkdir -p "${APPDIR}/usr/lib/python" \
         "${APPDIR}/usr/share/applications" \
         "${APPDIR}/usr/share/icons/hicolor/256x256/apps" \
         "${APPDIR}/usr/share/doc/parakeet-cage" \
         "${DIST_DIR}"

# --- application ------------------------------------------------------------
log "Copying application code"
cp -r "${PROJECT_ROOT}/parakeet_cage" "${APPDIR}/usr/lib/python/"
find "${APPDIR}/usr/lib/python" -type d -name '__pycache__' -prune -exec rm -rf {} +

# Attribution and license travel with the bundle (CC-BY-4.0 requires it).
cp "${PROJECT_ROOT}/README.md" "${PROJECT_ROOT}/LICENSE" "${PROJECT_ROOT}/CREDITS.md" "${APPDIR}/"
cp "${PROJECT_ROOT}/LICENSE" "${PROJECT_ROOT}/CREDITS.md" "${APPDIR}/usr/share/doc/parakeet-cage/"

# --- model weights ----------------------------------------------------------
# Placed where transcriber.DEFAULT_SEARCH_PATHS looks first:
#   <package parent>/models/parakeet-redux  ==  usr/lib/python/models/parakeet-redux
if [ "${BUNDLE_MODEL}" = "1" ]; then
  if [ ! -f "${MODEL_SRC}/model.safetensors" ] || [ ! -f "${MODEL_SRC}/config.json" ]; then
    echo "ERROR: no model weights in ${MODEL_SRC}" >&2
    echo "       set PARAKEET_MODEL_DIR, or PARAKEET_BUNDLE_MODEL=0 to build without them" >&2
    exit 1
  fi
  log "Bundling model weights from ${MODEL_SRC}"
  mkdir -p "${APPDIR}/usr/lib/python/models"
  cp -r "${MODEL_SRC}" "${APPDIR}/usr/lib/python/models/parakeet-redux"
else
  log "PARAKEET_BUNDLE_MODEL=0 - model weights not bundled"
fi

# --- desktop entry and icon -------------------------------------------------
log "Installing desktop entry and icon"
install -m 0644 "${PROJECT_ROOT}/packaging/parakeet-cage.desktop" "${APPDIR}/parakeet-cage.desktop"
install -m 0644 "${PROJECT_ROOT}/packaging/parakeet-cage.desktop" \
        "${APPDIR}/usr/share/applications/parakeet-cage.desktop"

python3 - "${APPDIR}" <<'PY'
import sys
from pathlib import Path

from PIL import Image, ImageDraw

appdir = Path(sys.argv[1])
img = Image.new("RGBA", (256, 256), color=(0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.ellipse([16, 16, 240, 240], fill="#2ecc71", outline="#27ae60", width=8)
img.save(appdir / "parakeet-cage.png")
img.save(appdir / ".DirIcon", format="PNG")
img.save(appdir / "usr/share/icons/hicolor/256x256/apps/parakeet-cage.png")
PY

# --- AppRun -----------------------------------------------------------------
log "Writing AppRun"
cat > "${APPDIR}/AppRun" <<'EOF'
#!/bin/bash
# Parakeet Cage AppRun - thin bundle: the host provides python3, PyGObject,
# dbus-python and the pip dependencies; the application code and the model
# weights live inside the bundle.
set -e
HERE="$(dirname "$(readlink -f "${0}")")"
export APPDIR="${HERE}"
export PYTHONPATH="${HERE}/usr/lib/python${PYTHONPATH:+:${PYTHONPATH}}"
export PATH="${HERE}/usr/bin${PATH:+:${PATH}}"
# Without this, "python3 -m" prepends the current directory to sys.path and a
# checkout (or any dir holding parakeet_cage/ or models/) would shadow the bundle.
export PYTHONSAFEPATH=1

if [ "${PARAKEET_SKIP_PREFLIGHT:-0}" != "1" ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Parakeet Cage: python3 is not on PATH. Install it (e.g. sudo dnf install python3)." >&2
    exit 1
  fi
  missing="$(python3 - <<'PY'
import importlib.util

needed = {
    "gi": "sudo dnf install python3-gobject",
    "dbus": "sudo dnf install dbus-python",
    "sounddevice": "pip install sounddevice",
    "numpy": "pip install numpy",
    "torch": "pip install torch",
    "kestrel": "pip install kestrel",
    "pystray": "pip install pystray",
    "PIL": "pip install pillow",
    "Xlib": "pip install python-xlib",
}
print("; ".join(f"{m} ({hint})" for m, hint in needed.items() if importlib.util.find_spec(m) is None))
PY
)"
  if [ -n "${missing}" ]; then
    echo "Parakeet Cage: missing host Python packages: ${missing}" >&2
    exit 1
  fi
fi

exec python3 -m parakeet_cage.app "$@"
EOF
chmod +x "${APPDIR}/AppRun"

# --- appimagetool -----------------------------------------------------------
if command -v "${APPIMAGETOOL:-appimagetool}" >/dev/null 2>&1; then
  APPIMAGETOOL="$(command -v "${APPIMAGETOOL:-appimagetool}")"
else
  APPIMAGETOOL="${BUILD_DIR}/appimagetool"
  if [ ! -x "${APPIMAGETOOL}" ]; then
    log "appimagetool not found - downloading it"
    curl -fsSL -o "${APPIMAGETOOL}" "${APPIMAGETOOL_URL}"
    chmod +x "${APPIMAGETOOL}"
  fi
fi

log "Running appimagetool"
ARCH=x86_64 "${APPIMAGETOOL}" --no-appstream "${APPDIR}" "${OUT}"

log "Built ${OUT} ($(du -h "${OUT}" | cut -f1))"
log "Note: running the AppImage needs libfuse2; without it use --appimage-extract-and-run"
