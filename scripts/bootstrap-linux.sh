#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${SAGAQUILL_REPO_URL:-https://github.com/goodgoodstudyboy/sagaquill-longform-lab.git}"
REF="${SAGAQUILL_REF:-main}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root, for example: curl -fsSL <bootstrap-url> | sudo bash" >&2
  exit 1
fi

install_packages_if_possible() {
  missing=()
  for cmd in git curl "${PYTHON_BIN}"; do
    command -v "${cmd}" >/dev/null 2>&1 || missing+=("${cmd}")
  done
  if [[ "${#missing[@]}" -eq 0 ]]; then
    return
  fi
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y git curl ca-certificates python3 python3-venv
    return
  fi
  echo "Missing required commands: ${missing[*]}" >&2
  echo "Install git, curl, Python 3.11+, and venv support, then retry." >&2
  exit 1
}

install_packages_if_possible

"${PYTHON_BIN}" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11+ is required.")
PY

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

git clone --depth 1 --branch "${REF}" "${REPO_URL}" "${tmp_dir}/sagaquill"
cd "${tmp_dir}/sagaquill"

exec bash scripts/install-linux.sh
