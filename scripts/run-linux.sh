#!/usr/bin/env bash
set -euo pipefail

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .

HOST="${SAGAQUILL_HOST:-127.0.0.1}"
PORT="${SAGAQUILL_PORT:-8765}"

if [[ "${HOST}" != "127.0.0.1" && "${HOST}" != "localhost" && -z "${SAGAQUILL_ACCESS_TOKEN:-}" ]]; then
  echo "Set SAGAQUILL_ACCESS_TOKEN before binding to ${HOST}." >&2
  exit 1
fi

exec sagaquill serve --host "${HOST}" --port "${PORT}"
