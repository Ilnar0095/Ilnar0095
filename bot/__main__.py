"""Запуск и самотест.

    python -m bot                # поллинг Telegram
    python -m bot --selftest     # офлайн-проверка: конфиг, генерация каркаса,
                                 # линтер репозитория, доступность ffmpeg/шрифта

Самотест не трогает Telegram и сеть: им удобно проверять образ перед деплоем.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from .config import Config
from .repo import Repo


async def selftest() -> int:
    cfg = Config.from_env()
    if not cfg.repo.exists():
        print(f"❌ репозиторий не найден: {cfg.repo} (задайте COOKRATE_REPO)")
        return 1
    repo = Repo(cfg)

    print(f"📂 {cfg.repo}")
    for name, on in cfg.status().items():
        print(f"   {'✅' if on else '—'} {name}")

    # 1. генерация текста
    from . import llm, media
    text, source = await llm.draft(cfg, repo, "post", "Груша в слоёном тесте с сыром")
    print(f"\n✍️  llm.draft: {len(text)} знаков, источник = {source}")
    if len(text) < 400:
        print("❌ каркас слишком короткий")
        return 1

    # 2. линтер репозитория
    res = repo.lint_text(text)
    if res is None:
        print("❌ cookrate не импортирован — проверьте dzen/tools/cookrate.py")
        return 1
    print(f"✅ repo.lint_text: ошибок {len(res.errors)}, предупреждений {len(res.warns)}")
    for e in res.errors[:3]:
        print(f"     ❌ {e}")

    # 3. нумерация и транслитерация слага
    from .repo import slugify
    number = repo.next_number()
    print(f"✅ next_number = {number}, slugify = {slugify('Груша в слоёном тесте')}")

    # 4. подпись обложки
    cap = media.caption_from(text)
    print(f"✅ media.caption_from → {cap!r}")

    # 5. промпт Анжелы
    prompt = repo.angela_prompt()
    print(f"{'✅' if prompt else '❌'} angela_prompt: {len(prompt)} знаков")

    # 6. план
    plan = repo.plan(1)
    print(f"{'✅' if plan and 'TODO' not in plan else '❌'} план недели 1: {len(plan.splitlines())} строк")

    print("\n" + ("⚠️  ffmpeg нет: обложки/тизеры будут недоступны до сборки Docker-образа"
                  if not cfg.has_ffmpeg else "✅ ffmpeg на месте"))
    print("selftest: OK" if prompt else "selftest: есть провалы")
    return 0 if prompt else 1


def check_token() -> int:
    """Проверка токена до запуска: getMe должен вернуть имя вашего бота."""
    import asyncio

    import aiohttp

    cfg = Config.from_env()
    if not cfg.token:
        print("❌ TELEGRAM_BOT_TOKEN пуст. Скопируйте строку из @BotFather в bot/.env")
        return 2

    async def probe() -> tuple[int, str]:
        url = f"https://api.telegram.org/bot{cfg.token}/getMe"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as s:
                async with s.get(url) as r:
                    return r.status, await r.text()
        except Exception as exc:
            return -1, f"нет доступа к Telegram API: {exc}"

    status, raw = asyncio.run(probe())
    if status == 200:
        import json
        r = json.loads(raw).get("result", {})
        print(f"✅ токен рабочий. Бот: «{r.get('first_name')}» @{r.get('username')}")
        print("Теперь напишите ему /start и запускайте:  python -m bot")
        return 0
    print(f"❌ Telegram ответил {status}: {raw[:300]}")
    print("Обычно это значит: токен скопирован не полностью (нужны обе части через двоеточие) "
          "или бота пересоздали — возьмите новый через /revoke.")
    return 1


def run() -> int:
    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties

    from .handlers import router

    cfg = Config.from_env()
    if not cfg.token:
        print("❌ TELEGRAM_BOT_TOKEN пуст. Скопируйте bot/.env.example в bot/.env и впишите токен @BotFather.")
        return 2
    repo = Repo(cfg)

    async def main() -> None:
        # parse_mode намеренно выключен: тексты каналов полны markdown-разметки,
        # и Telegram резал бы её как свои тег
        bot = Bot(cfg.token, default=DefaultBotProperties(parse_mode=None))
        dp = Dispatcher()
        dp.include_router(router)
        bot.cookrate_cfg = cfg          # type: ignore[attr-defined]
        bot.cookrate_repo = repo        # type: ignore[attr-defined]
        status = ", ".join(f"{k}:{'да' if v else 'нет'}" for k, v in cfg.status().items())
        print(f"🍳 COOKRATE bot запущен. {status}")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("остановлено")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(asyncio.run(selftest()))
    if "--check-token" in sys.argv:
        sys.exit(check_token())
    sys.exit(run())
