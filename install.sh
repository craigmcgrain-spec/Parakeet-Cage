#!/usr/bin/env bash
# Parakeet Cage installer. See README.md -> Install.
#
#   ./install.sh                 interactive: asks before downloading the model
#   ./install.sh --yes           non-interactive: install the app and the model
#   ./install.sh --no-model      install the app only
#   ./install.sh --skip-app      skip pip; install the launcher and weights only
#   ./install.sh --no-desktop    do not install the application menu entry
#
# Runs parakeet_cage/install.py with whatever python3 is on PATH: the installer
# itself needs nothing but the standard library.
set -euo pipefail

HERE="$(dirname "$(readlink -f "${0}")")"
PYTHON="${PYTHON:-python3}"

if ! command -v "${PYTHON}" >/dev/null 2>&1; then
  printf 'install.sh: %s not found on PATH; install Python 3.11+ first\n' "${PYTHON}" >&2
  exit 1
fi

cd "${HERE}"
exec "${PYTHON}" -m parakeet_cage.install "$@"
