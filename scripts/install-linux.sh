#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/sagaquill}"
ENV_DIR="${ENV_DIR:-/etc/sagaquill}"
SERVICE_NAME="${SERVICE_NAME:-sagaquill}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
HOST="${SAGAQUILL_HOST:-127.0.0.1}"
PORT="${SAGAQUILL_PORT:-8765}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/install-linux.sh" >&2
  exit 1
fi

command -v "${PYTHON_BIN}" >/dev/null 2>&1 || {
  echo "Python 3.11+ is required." >&2
  exit 1
}

"${PYTHON_BIN}" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11+ is required.")
PY

mkdir -p "${APP_DIR}" "${ENV_DIR}" "${APP_DIR}/runs" "${APP_DIR}/.sagaquill"
find "${APP_DIR}" -mindepth 1 \
  ! -path "${APP_DIR}/runs" \
  ! -path "${APP_DIR}/runs/*" \
  ! -path "${APP_DIR}/.sagaquill" \
  ! -path "${APP_DIR}/.sagaquill/*" \
  -exec rm -rf {} +
tar \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='runs' \
  --exclude='.sagaquill' \
  --exclude='.novel*' \
  --exclude='material' \
  -cf - . | tar -xf - -C "${APP_DIR}"

"${PYTHON_BIN}" -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install "${APP_DIR}"

if [[ ! -f "${ENV_DIR}/sagaquill.env" ]]; then
  TOKEN="$("${PYTHON_BIN}" - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
  cat > "${ENV_DIR}/sagaquill.env" <<EOF
SAGAQUILL_HOST=${HOST}
SAGAQUILL_PORT=${PORT}
SAGAQUILL_ACCESS_TOKEN=${TOKEN}
SAGAQUILL_CONTINUATION_MODE=hybrid
EOF
  chmod 600 "${ENV_DIR}/sagaquill.env"
fi

cp "${APP_DIR}/deploy/sagaquill.service" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"
systemctl restart "${SERVICE_NAME}.service"

echo "SagaQuill installed."
echo "URL: http://${HOST}:${PORT}"
echo "Token file: ${ENV_DIR}/sagaquill.env"
