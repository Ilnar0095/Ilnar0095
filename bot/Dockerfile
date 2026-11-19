FROM python:3.11-slim-bookworm

# ffmpeg — обложки и тизеры; fonts-dejavu-core — кириллица в drawtext;
# git — бот может сам коммитить черновики, если вы это включите
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY bot/requirements.txt /app/bot/requirements.txt
RUN pip install --no-cache-dir -r /app/bot/requirements.txt

# в образ кладём только бота и чек-лист-тулинг: тексты канала монтируются томом,
# чтобы черновики из Telegram попадали в вашу рабочую копию репозитория
COPY bot /app/bot
COPY dzen /app/dzen

ENV PYTHONPATH=/app \
    COOKRATE_REPO=/app \
    PYTHONUNBUFFERED=1

# проверка сборки перед стартом: конфиг, каркас текста, линтер, ffmpeg
RUN python -m bot --selftest || true

CMD ["python", "-m", "bot"]
