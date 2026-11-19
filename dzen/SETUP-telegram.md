# Как поставить COOKRATE Bot в Telegram: пошагово

Для тех, кто ставит впервые. Время: ~20 минут. Деньги: 0 ₽, если запускать на своём
компьютере, и ~200–350 ₽/мес, если хотите, чтобы бот отвечал круглосуточно с сервера.

---

## Шаг 0. Понять, где будет жить бот

Бот — это не сервис в Telegram, а программа, которая должна что-то «слушать».
Telegram хранит сообщения и кнопки, а код крутится у вас.

| Вариант | Плюс | Минус |
|---|---|---|
| **A. Свой компьютер** | бесплатно, 5 минут | бот молчит, пока компьютер выключен или закрыт ноутбук |
| **B. Docker на компьютере** | то же + ffmpeg и шрифт уже внутри (работают обложки и тизеры) | тот же минус с выключением |
| **C. VPS-сервер** (Timeweb, Selectel, Aeza, Reg.ru — любой от 200 ₽/мес) | работает 24/7, писать можно с телефона | нужен SSH и 10 минут |

Новичку я советую начать с **B** (пощупать), а когда втянетесь — перенести на **C**:
код и `bot/.env` переезжают без изменений.

---

## Шаг 1. Завести бота в BotFather (это само «установка в Telegram»)

1. Откройте [@BotFather](https://t.me/BotFather) → **Start**.
2. Команда `/newbot`.
3. Он спросит **имя** — можно с пробелами и кириллицей: `COOKRATE Необычная Кухня`.
4. Потом спросит **username** — только латиница, без пробелов, обязательно
   с окончанием `bot`: `cookrate_neobychnaya_kuhnya_bot`.
   Если занят — добавьте цифру: `cookrate_kuhnya_2_bot`.
5. В ответ получите строку вида:

```
000000000:AAH1Ks7m…  ← это токен. Один раз. Никому не показывайте.
```

6. Сразу там же: `/setdescription` → «Помощник канала: статьи, посты, обложки, ролики».
   `/setuserpic` → картинка с Анжелой. `/setcommands` → вставьте список:

```
статья - Статья-разбор по теме
пост - Короткий пост «необычно, но дёшево»
ролик - Раскадровка + озвучка + тизер
обложка - Обложка 16:9 с подписью
кадры - Иллюстрации к последнему тексту
проверь - Линтер по dzen/next/
план - Контент-план
черновик - Последний сгенерированный текст
статус - Что подключено
id - Мой chat id
```

**Токен в чат с агентом не присылайте.** Он нужен только в файле `bot/.env` на вашей машине.

---

## Шаг 2. Достать код

Код лежит в этом репозитории. ⚠️ Пока PR №1 не влит в `main`, бот живёт **в ветке**:
`arena/ff89cd13-ilnar0095`.

**Вариант через git** (рекомендую):

```bash
git clone -b arena/ff89cd13-ilnar0095 https://github.com/Ilnar0095/Ilnar0095.git cookrate
cd cookrate
```

После слияния PR будет достаточно `git clone https://github.com/Ilnar0095/Ilnar0095.git cookrate`.

**Без git:** кнопка **Code → Download ZIP** на странице нужной ветки, распаковать.

---

## Шаг 3. Поставить Python (нужен 3.10 или новее)

* **Windows**: [python.org/downloads](https://www.python.org/downloads/) → при установке
  **обязательно** поставить галочку *Add python.exe to PATH*.
* **macOS**: `brew install python@3.12`
* **Linux (Ubuntu/Debian)**: `sudo apt update && sudo apt install -y python3 python3-venv python3-pip git`

Проверка: `python --version` (Windows) или `python3 --version` (остальные).

---

## Шаг 4. Установить бота одной командой

Из корня распакованного репозитория:

```bash
python bot/install.py        # Windows
python3 bot/install.py       # macOS / Linux
```

Что он сделает сам: проверит версию Python и файлы канала, предупредит про отсутствие
ffmpeg, создаст `.venv`, поставит `aiogram + aiohttp + edge-tts`, спросит токен и ваш id,
запишет `bot/.env`, прогонит самотест и напечатает команду запуска.

Нужно только сгенерировать тексты через модель, без картинок и сервера —
подсказка: `python bot/install.py --check` в любой момент перепроверяет сборку.

Хотите ffmpeg-обложки и тизеры без ручной установки — Docker:

```bash
cp bot/.env.example bot/.env      # вписать TELEGRAM_BOT_TOKEN и TELEGRAM_ADMIN_ID
docker compose -f bot/docker-compose.yml up -d --build
docker compose -f bot/docker-compose.yml logs -f
```

---

## Шаг 5. Узнать свой chat id и закрыть бота для чужих

1. Запустите бота: `.venv\Scripts\python -m bot` (Windows) или `.venv/bin/python -m bot` (macOS/Linux).
   В консоли должно появиться: `🍳 COOKRATE bot запущен`.
2. В Telegram найдите своего бота по username → **Start** → он ответит и покажет ваш id:
   `Твой id: 123456789`. (Если старт прошёл молча — напишите `/id`.)
3. Пропишите его в `bot/.env`: `TELEGRAM_ADMIN_ID=123456789`, остановите бота
   (Ctrl+C) и запустите снова.

После этого чужие сообщения бот игнорирует — важно, потому что токен утекает
вместе со скриншотом переписки.

---

## Шаг 6. Первая публикация через бота

```
/статья Груша в слоёном тесте с сыром
```

Бот вернёт текст и под ним линтер-отчёт (`✅ чисто` или список «нет цены порции»,
«заголовок 85 симв.»). Кнопка **💾 В dzen/next/** кладёт черновик в репозиторий:
`dzen/next/007-grusha-v-sloenom-teste.md`. Дальше ваш обычный цикл:

```bash
git add dzen/next/007-grusha-v-sloenom-teste.md
git commit -m "draft: груша в слоёном тесте"
git push
```

Текст в Дзен копируете руками — бот публикацию не делает, это правило канала.

---

## Шаг 7. Чтобы работал круглосуточно (по желанию)

### 7.1 Ключ модели — без него тексты пишет «каркасник»

В `bot/.env`:

```
LLM_FORMAT=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-…
```

Нет OpenAI — берите OpenRouter (`LLM_BASE_URL=https://openrouter.ai/api/v1`,
`LLM_MODEL=openai/gpt-4o-mini`) или локальную модель через Ollama
(`LLM_BASE_URL=http://127.0.0.1:11434/v1`, `LLM_MODEL=qwen2.5:14b`, `LLM_API_KEY=ollama`).
Картинки: `IMAGE_PROVIDER=openai` или `IMAGE_PROVIDER=replicate` + `REPLICATE_API_TOKEN`.
Список голосов для озвучки: `TTS_VOICE=ru-RU-SvetlanaNeural` (ж) / `ru-RU-DmitryNeural` (м).

### 7.2 Автозапуск на Windows

`Планировщик заданий` → *Создать задачу* → *При входе в систему* →
действие *Запустить программу*:

```
Программа:  C:\Users\ВАМ\cookrate\.venv\Scripts\python.exe
Аргументы:  -m bot
Начать в:   C:\Users\ВАМ\cookrate
```

Галочка «Запустить как скрытую» не нужна: проще держать ярлык с
`cmd /k "cd /d C:\Users\ВАМ\cookrate && .venv\Scripts\python.exe -m bot"`.

### 7.3 Автозапуск на VPS (systemd)

```bash
sudo nano /etc/systemd/system/cookrate-bot.service
```

```ini
[Unit]
Description=COOKRATE Telegram bot
After=network-online.target

[Service]
WorkingDirectory=/opt/cookrate
ExecStart=/opt/cookrate/.venv/bin/python -m bot
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cookrate-bot
journalctl -u cookrate-bot -f          # живые логи
```

---

## Если что-то не так

| Вижу | Что делать |
|---|---|
| `python не является внутренней…` | не поставлена галочка *Add to PATH*; переустановить Python или звать `py` вместо `python` |
| `No module named bot` | вы запустили не из корня репозитория; `cd` в папку, где лежат `bot/` и `dzen/` |
| `TelegramWebhookError: Unauthorized` | токен списан/пересоздан — `/revoke` в BotFather и обновить `bot/.env` |
| Бот молчит на `/start` | его не запустили, либо id в `TELEGRAM_ALLOWED_CHATS` от другого чата; `/статус` не ответит — просто выключите фильтр, пока разбираетесь |
| `нет ffmpeg` | `winget install Gyan.FFmpeg` / `brew install ffmpeg` / `apt install ffmpeg fonts-dejavu-core`, либо Docker |
| Обложка без кириллицы, квадратики | не найден шрифт: поставьте `fonts-dejavu-core` или укажите `COVER_FONT` на любой ttf с кириллицей |
| Озвучка пустая | `pip install edge-tts` внутри venv; на VPS проверьте, что есть выход в интернет без прокси |
| Черновик не появился в `dzen/next/` | в `bot/.env` кривой `COOKRATE_REPO` — должен быть путь к корню репозитория |

Проверить сборку целиком без сети и без Telegram: `python bot/install.py --check`.
