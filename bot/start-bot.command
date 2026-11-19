#!/bin/bash
# Двойной клик на macOS: ставит зависимости при первом запуске и поднимает бота.
cd "$(dirname "$0")/.." || exit 1
PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "Python не найден. Поставьте: brew install python@3.12"
  read -r -p "Enter, чтобы закрыть…" _
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "[шаг 1 из 2] Первый запуск: ставлю зависимости (1–2 минуты)"
  "$PY" bot/install.py || { read -r -p "Enter, чтобы закрыть…" _; exit 1; }
fi
echo "[шаг 2 из 2] Запускаю бота. Не закрывайте это окно."
.venv/bin/python -m bot
read -r -p "Бот остановлен. Enter, чтобы закрыть…" _
