#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRESET_DIR="${ROOT_DIR}/private_presets/helix_seed_local"

if [[ ! -d "${PRESET_DIR}" ]]; then
  echo "Private preset not found at ${PRESET_DIR}" >&2
  echo "Run: python3 scripts/build_private_helix_seed.py" >&2
  exit 1
fi

cd "${ROOT_DIR}"
export HELIX_DATA_DIR="private_presets/helix_seed_local"
export HELIX_DISABLE_TELEGRAM="${HELIX_DISABLE_TELEGRAM:-1}"
exec python3 main.py "$@"
