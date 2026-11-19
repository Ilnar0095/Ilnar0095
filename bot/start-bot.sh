#!/usr/bin/env bash
# Первый запуск на своём ПК или на сервере. Для 24/7 на сервере удобнее systemd
# (см. dzen/SETUP-telegram.md, шаг 7.3).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="$(command -v python3 || command -v python)"
if [ ! -x .venv/bin/python ]; then
  echo "[шаг 1 из 2] Первый запуск: ставлю зависимости"
  "$PY" bot/install.py
fi
echo "[шаг 2 из 2] Запускаю бота (остановить: Ctrl+C)"
exec .venv/bin/python -m bot
