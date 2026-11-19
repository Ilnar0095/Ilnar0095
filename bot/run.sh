#!/usr/bin/env bash
# Локальный запуск без Docker: venv + зависимости + selftest + поллинг.
# Нужен ffmpeg в системе для обложек/тизеров: apt install ffmpeg / brew install ffmpeg
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r bot/requirements.txt

export COOKRATE_REPO="$PWD"
python -m bot --selftest
if [ "${1:-}" = "--selftest-only" ]; then exit 0; fi
exec python -m bot
