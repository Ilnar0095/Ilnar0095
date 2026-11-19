"""Хендлеры Telegram-бота COOKRATE.

UX построен вокруг репозитория, а не вокруг чата: бот генерирует текст, сам себя
проверяет линтером канала, сохраняет черновик в dzen/next/ и там же берёт референсы
для обложек. Всё, что требует денег снаружи (LLM, картинки, видео), опционально и
честно признаётся кнопкой «статус».
"""
from __future__ import annotations

import re
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, InputMediaPhoto, Message)

from . import llm, media
from .repo import Repo

router = Router()
LIMIT = 3800  # запас до лимита Telegram в 4096

BUTTONS_MENU = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📝 Статья", callback_data="g:article"),
     InlineKeyboardButton(text="⚡ Пост", callback_data="g:post"),
     InlineKeyboardButton(text="🎬 Ролик", callback_data="g:video")],
    [InlineKeyboardButton(text="🖼 Обложка", callback_data="a:cover"),
     InlineKeyboardButton(text="🖨 Кадры", callback_data="a:shots"),
     InlineKeyboardButton(text="🔊 Озвучка", callback_data="a:audio")],
    [InlineKeyboardButton(text="📋 План", callback_data="u:plan"),
     InlineKeyboardButton(text="✅ Проверить всё", callback_data="u:lint"),
     InlineKeyboardButton(text="⚙️ Статус", callback_data="u:status")],
])


class Pending(StatesGroup):
    topic = State()


def kb_last_text() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Переписать", callback_data="a:regen"),
         InlineKeyboardButton(text="✅ Проверить текст", callback_data="a:lint")],
        [InlineKeyboardButton(text="💾 В dzen/next/", callback_data="a:save"),
         InlineKeyboardButton(text="🖼 Обложка", callback_data="a:cover")],
        [InlineKeyboardButton(text="🖨 3 кадра (ИИ)", callback_data="a:shots"),
         InlineKeyboardButton(text="🎞 Тизер 15 сек", callback_data="a:teaser")],
        [InlineKeyboardButton(text="🔊 Озвучка", callback_data="a:audio")],
    ])


def kb_topic() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="u:menu")],
    ])


async def send_long(message: Message, text: str, reply=None) -> None:
    parts, buf = [], ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > LIMIT:
            parts.append(buf)
            buf = line
        else:
            buf += line
    if buf.strip():
        parts.append(buf)
    for i, part in enumerate(parts):
        kwargs = {"reply_markup": reply} if i == len(parts) - 1 else {}
        await message.answer(part, **kwargs)


def read_text(state_data: dict, repo: Repo) -> tuple[str, str, str]:
    """(текст, вид, тема) — из памяти сессии или со свежий черновик из репозитория."""
    text = state_data.get("text") or ""
    kind = state_data.get("kind") or "post"
    topic = state_data.get("topic") or ""
    if not text:
        files = sorted((repo.next_dir).glob("*.md"))
        if files:
            newest = files[-1]
            text = newest.read_text(encoding="utf-8")
            topic = newest.stem
            kind = "article" if "article" in text[:400] else "post"
            return text, kind, topic
    return text, kind, topic


# --- служебные ------------------------------------------------------------------


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    chat = message.chat.id
    await message.answer(
        f"COOKRATE Bot. Твой id: <b>{chat}</b> — он нужен в TELEGRAM_ADMIN_ID.\n\n"
        "Я пишу статьи и посты по правилам канала, проверяю их линтером, собираю "
        "обложки, кадры, тизеры и озвучку. Черновики кладутся прямо в репозиторий, "
        "в dzen/next/.",
        reply_markup=BUTTONS_MENU)


@router.message(Command("id"))
async def cmd_id(message: Message):
    await message.answer(f"chat id: {message.chat.id}")


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Команды:\n"
        "/статья <тема> — разбор на 2500–3500 знаков\n"
        "/пост <тема> — короткий пост «необычно, но дёшево»\n"
        "/ролик <тема> — раскадровка + озвучка + тизер\n"
        "/обложка — 16:9 с подписью по стилю Анжелы\n"
        "/кадры — 3 иллюстрации к последнему тексту (нужен IMAGE_PROVIDER)\n"
        "/тизер — склейка кадров в 15-секундный ролик\n"
        "/озвучка — русский голос из «Текста за кадром»\n"
        "/проверь — линтер по всем dzen/next/*.md\n"
        "/план [неделя] — что выходит\n"
        "/черновик — последний сгенерированный текст\n"
        "/статус — что подключено (LLM, картинки, видео, ffmpeg)\n\n"
        "Любое сообщение без слэша = тема для генерации, если вы только что нажали "
        "кнопку «Статья/Пост/Ролик».")


@router.message(Command("статус"))
@router.message(Command("status"))
async def cmd_status(message: Message, bot: Bot):
    cfg = bot.cookrate_cfg  # type: ignore[attr-defined]
    lines = [f"📂 репозиторий: {cfg.repo}"]
    for name, on in cfg.status().items():
        lines.append(f"{'✅' if on else '️'} {name}")
    lines.append("Подключается правкой bot/.env и `docker compose restart`.")
    await message.answer("\n".join(lines))


@router.callback_query(F.data == "u:status")
async def cb_status(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    await cmd_status(callback.message, bot)  # type: ignore[arg-type]


@router.callback_query(F.data == "u:menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Меню:", reply_markup=BUTTONS_MENU)  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "u:plan")
async def cb_plan(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    repo: Repo = callback.message.bot.cookrate_repo  # type: ignore[union-attr]
    await callback.message.answer("Контент-план:\n" + repo.plan())  # type: ignore[union-attr]


# --- генерация текстов -----------------------------------------------------------


async def start_generation(message: Message, state: FSMContext, kind: str, topic: str = "") -> None:
    if topic:
        await run_generation(message, state, kind, topic)
        return
    await state.set_state(Pending.topic)
    await state.update_data(kind=kind)
    label = {"article": "статьи-разбора", "post": "поста", "video": "роликам"}[kind]
    await message.answer(f"Тема для {label}? Напишите одной строкой, "
                         f"например: «Груша в слоёном тесте с сыром».",
                         reply_markup=kb_topic())


@router.callback_query(F.data.startswith("g:"))
async def cb_generate(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    kind = callback.data.split(":", 1)[1]  # type: ignore[union-attr]
    await start_generation(callback.message, state, kind)  # type: ignore[arg-type]


for alias, kind in (("статья", "article"), ("article", "article"),
                    ("пост", "post"), ("post", "post")):

    def _make(kind=kind):
        async def handler(message: Message, state: FSMContext):
            topic = (message.text or "").split(maxsplit=1)
            await start_generation(message, state, kind, topic[1] if len(topic) > 1 else "")
        return handler

    router.message.register(_make(), Command(alias))


@router.message(Pending.topic)
async def on_topic(message: Message, state: FSMContext):
    data = await state.get_data()
    kind = data.get("kind", "post")
    topic = (message.text or "").strip()
    await state.clear()
    await run_generation(message, state, kind, topic)


async def run_generation(message: Message, state: FSMContext, kind: str, topic: str) -> None:
    if not topic:
        await message.answer("Нужна тема — напишите её следующим сообщением.")
        return
    bot: Bot = message.bot  # type: ignore[assignment]
    cfg = bot.cookrate_cfg  # type: ignore[attr-defined]
    repo: Repo = bot.cookrate_repo  # type: ignore[attr-defined]

    await bot.send_chat_action(message.chat.id, "typing")
    try:
        text, source = await llm.draft(cfg, repo, kind, topic)
    except Exception as exc:
        await message.answer(f"Модель не ответила: {str(exc)[:400]}\n"
                             "Проверьте LLM_API_KEY и LLM_BASE_URL в bot/.env.")
        return

    await state.update_data(text=text, kind=kind, topic=topic)
    lint = repo.lint_text(text)

    head = ("✍️ текст пишет модель " + (cfg.llm_model or "")) if source == "llm" \
        else "⚠️ LLM не подключён — собрал каркас по правилам канала и задал вопросы автору"
    await message.answer(head)
    await send_long(message, text, reply=kb_last_text())
    if lint:
        await message.answer(lint.report())
    if cfg.autosave and source == "llm":
        path = repo.save_draft(text, kind=kind, topic=topic)
        await message.answer(f"💾 черновик сохранён: {path.relative_to(repo.root)}\n"
                             f"коммит: git add {path.relative_to(repo.root)} && "
                             f"git commit -m 'draft: {topic}'")


@router.callback_query(F.data == "a:regen")
async def cb_regen(callback: CallbackQuery, state: FSMContext):
    await callback.answer("переписываю")
    data = await state.get_data()
    if not data.get("topic"):
        await callback.message.answer("Тема потерялась — нажите «Статья» и пришлите тему заново.")  # type: ignore[union-attr]
        return
    await run_generation(callback.message, state, data.get("kind", "post"), data["topic"])  # type: ignore[arg-type]


@router.callback_query(F.data == "a:lint")
async def cb_lint(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    repo: Repo = callback.message.bot.cookrate_repo  # type: ignore[union-attr]
    if not data.get("text"):
        await callback.message.answer("Нет текста в памяти сессии. /черновик не найден.")  # type: ignore[union-attr]
        return
    res = repo.lint_text(data["text"])
    await callback.message.answer(res.report() if res else "Линтер недоступен")  # type: ignore[union-attr]


@router.callback_query(F.data == "a:save")
async def cb_save(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    repo: Repo = callback.message.bot.cookrate_repo  # type: ignore[union-attr]
    if not data.get("text"):
        await callback.message.answer("Нечего сохранять.")  # type: ignore[union-attr]
        return
    path = repo.save_draft(data["text"], kind=data.get("kind", "post"), topic=data.get("topic", "topic"))
    await callback.message.answer(f"💾 сохранён {path.relative_to(repo.root)}")  # type: ignore[union-attr]
    await callback.message.answer_document(FSInputFile(path))  # type: ignore[union-attr]


@router.message(Command("черновик"))
async def cmd_draft(message: Message, state: FSMContext):
    data = await state.get_data()
    text, _, _ = read_text(data, message.bot.cookrate_repo)  # type: ignore[union-attr]
    if not text:
        await message.answer("Черновиков нет. /пост <тема>")
        return
    await send_long(message, text, reply=kb_last_text())


# --- медиа -----------------------------------------------------------------------


async def _media_dir(bot: Bot, name: str) -> Path:
    d = Path(bot.cookrate_cfg.workdir) / name  # type: ignore[attr-defined]
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.callback_query(F.data == "a:cover")
async def cb_cover(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    bot: Bot = callback.message.bot  # type: ignore[assignment]
    repo: Repo = bot.cookrate_repo
    data = await state.get_data()
    text, _, topic = read_text(data, repo)
    if not text:
        await callback.message.answer("Нужен текст: сначала /статья или /пост.")  # type: ignore[union-attr]
        return
    res = await media.cover(bot.cookrate_cfg, repo, text, await _media_dir(bot, "covers"))
    if not res.ok:
        await callback.message.answer(f"Обложка: {res.hint}")  # type: ignore[union-attr]
        return
    await bot.send_photo(callback.message.chat.id, FSInputFile(res.files[0]),  # type: ignore[union-attr]
                        caption=f"Обложка 16:9 — {topic or 'без темы'}")
    await callback.message.answer(  # type: ignore[union-attr]
        "Превью. Настоящий кадр с Анжелой генерируется по IMAGE_PROVIDER; "
        "здесь взят референс из dzen/assets/ и наложена подпись по правилу из dzen/angela.md.")


async def _shot_prompts(cfg, repo: Repo, text: str, topic: str) -> list[str]:
    base = repo.angela_prompt()
    dish = topic or (re.search(r"^#\s+(.+)$", text, re.M).group(1) if re.search(r"^#\s+(.+)$", text, re.M) else "блюдо")
    dish_block = re.search(r"Dish:\s*\*\*.*?\*\*", base, re.S)
    prompts = []
    for angle in ("готовое блюдо крупно, ложка соуса течёт",
                  "руки в кадре: последний шаг, пар, глянцевый соус",
                  "тарелка на деревянном столе, свет из окна, порция для гостей"):
        p = base
        if dish_block:
            p = base.replace(dish_block.group(0), f"Dish: **{dish} — {angle}**")
        prompts.append(re.sub(r"\s+", " ", p))
    return prompts


@router.callback_query(F.data == "a:shots")
async def cb_shots(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await cb_illustrations(callback.message, state, count=3)


@router.message(Command("кадры"))
async def cmd_shots(message: Message, state: FSMContext, count: int = 3):
    await cb_illustrations(message, state, count=count)


async def cb_illustrations(message, state: FSMContext, count: int = 3) -> None:
    bot: Bot = message.bot  # type: ignore[assignment]
    repo: Repo = bot.cookrate_repo
    cfg = bot.cookrate_cfg
    data = await state.get_data()
    text, _, topic = read_text(data, repo)
    if not cfg.can_draw:
        await message.answer(
            "⛔️ генерация картинок выключена: IMAGE_PROVIDER=none.\n"
            "Включается в bot/.env: `IMAGE_PROVIDER=openai` (нужен LLM_API_KEY с доступом "
            "к gpt-image-1) или `IMAGE_PROVIDER=replicate` + REPLICATE_API_TOKEN + IMAGE_MODEL.\n"
            f"Промпт я уже собрал по стилю Анжелы, его можно скормить любой нейросети руками: "
            f"напишите /промпт.")
        await state.update_data(shots_prompt=(await _shot_prompts(cfg, repo, text or topic, topic))[0])
        return
    prompts = await _shot_prompts(cfg, repo, text or topic, topic)
    await message.answer(f"🖨 генерирую {len(prompts)} кадр(ов)… это минута.")
    res = await media.ai_images(cfg, prompts, await _media_dir(bot, "shots"))
    if not res.ok:
        await message.answer(f"Кадры: {res.hint}")
        return
    await bot.send_media_group(message.chat.id,  # type: ignore[union-attr]
                               [InputMediaPhoto(media=FSInputFile(p)) for p in res.files])
    await message.answer("Готово. Если лицо/фартук/кухня съехали — пересобрать: /кадры")


@router.message(Command("промпт"))
async def cmd_prompt(message: Message, state: FSMContext):
    data = await state.get_data()
    prompt = data.get("shots_prompt")
    if not prompt:
        repo: Repo = message.bot.cookrate_repo  # type: ignore[union-attr]
        prompt = (await _shot_prompts(message.bot.cookrate_cfg, repo, "", "мандарины в беконе"))[0]  # type: ignore[attr-defined]
    await send_long(message, prompt)


@router.callback_query(F.data == "a:audio")
async def cb_audio(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await send_audio(callback.message, state)


@router.message(Command("озвучка"))
async def cmd_audio(message: Message, state: FSMContext):
    await send_audio(message, state)


async def send_audio(message: Message, state: FSMContext) -> None:
    bot: Bot = message.bot  # type: ignore[assignment]
    repo: Repo = bot.cookrate_repo
    data = await state.get_data()
    text, kind, _ = read_text(data, repo)
    if not text:
        await message.answer("Нужен сценарий или статья: /ролик <тема>")
        return
    await message.answer("🔊 озвучиваю…")
    res = await media.speech(bot.cookrate_cfg, text, await _media_dir(bot, "voice"))
    if not res.ok:
        await message.answer(f"Озвучка: {res.hint}")
        return
    await bot.send_voice(message.chat.id, FSInputFile(res.files[0]))  # type: ignore[union-attr]


@router.callback_query(F.data == "a:teaser")
async def cb_teaser(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await make_teaser(callback.message, state)


@router.message(Command("тизер"))
async def cmd_teaser(message: Message, state: FSMContext):
    await make_teaser(message, state)


async def make_teaser(message: Message, state: FSMContext, vertical: bool = False) -> None:
    bot: Bot = message.bot  # type: ignore[assignment]
    cfg = bot.cookrate_cfg
    repo: Repo = bot.cookrate_repo
    data = await state.get_data()

    dest = await _media_dir(bot, "teaser")
    images = sorted((Path(cfg.workdir) / "shots").glob("shot-*.png")) if (Path(cfg.workdir) / "shots").exists() else []
    cover_src = repo.cover_source()
    if not images and cover_src:
        res = await media.cover(cfg, repo, data.get("text") or "", dest, source=cover_src)
        images = res.files
    if not images:
        await message.answer("Нет кадров для тизера: сначала /кадры (ИИ) или положите png в dzen/assets/.")
        return

    if cfg.can_video:
        vres = await media.ai_video(cfg, "cooking: glossy dish, hands plating, steam, warm daylight kitchen", dest)
        if vres.ok:
            await bot.send_video(message.chat.id, FSInputFile(vres.files[0]),  # type: ignore[union-attr]
                                 caption="тизер от видеомодели")
            return
        await message.answer(f"видеомодель недоступна ({vres.hint}) — собираю слайдшоу из кадров.")

    audio = (Path(cfg.workdir) / "voice" / "voice.mp3")
    text = data.get("text") or ""
    if text:
        ares = await media.speech(cfg, text, Path(cfg.workdir) / "voice")
        if ares.ok:
            audio = ares.files[0]
    await message.answer(f"🎞 склеиваю {len(images)} кадр(ов) по 3 секунды…")
    res = await media.slideshow(cfg, images[:5], dest,
                               audio=audio if Path(audio).exists() else None, vertical=vertical)
    if not res.ok:
        await message.answer(f"Тизер: {res.hint}")
        return
    await bot.send_video(message.chat.id, FSInputFile(res.files[0]),  # type: ignore[union-attr]
                         caption="Тизер 16:9 из готовых кадров. Для 9:16 — /тизер9")


@router.message(Command("тизер9"))
async def cmd_teaser9(message: Message, state: FSMContext):
    await make_teaser(message, state, vertical=True)


@router.message(Command("обложка"))
async def cmd_cover(message: Message, state: FSMContext):
    bot: Bot = message.bot  # type: ignore[assignment]
    repo: Repo = bot.cookrate_repo
    data = await state.get_data()
    text, _, _ = read_text(data, repo)
    if not text:
        await message.answer("Нужен текст: /статья <тема>")
        return
    res = await media.cover(bot.cookrate_cfg, repo, text, await _media_dir(bot, "covers"))
    if not res.ok:
        await message.answer(f"Обложка: {res.hint}")
        return
    await message.answer_photo(FSInputFile(res.files[0]))


@router.message(Command("ролик"))
async def cmd_video_full(message: Message, state: FSMContext):
    """Полный цикл: раскадровка → озвучка → тизер."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1:
        await run_generation(message, state, "video", parts[1].strip())
    await send_audio(message, state)
    await make_teaser(message, state)


# --- линт и план ------------------------------------------------------------------


@router.callback_query(F.data == "u:lint")
async def cb_lint_all(callback: CallbackQuery):
    await callback.answer()
    await lint_all(callback.message)  # type: ignore[arg-type]


@router.message(Command("проверь"))
@router.message(Command("check"))
async def lint_all(message: Message):
    repo: Repo = message.bot.cookrate_repo  # type: ignore[union-attr]
    files = sorted(repo.next_dir.glob("*.md")) if repo.next_dir.exists() else []
    if not files:
        await message.answer("В dzen/next/ пусто — нечего проверять.")
        return
    bad = 0
    out = []
    for f in files:
        res = repo.lint(f)
        if res is None:
            out.append("линт недоступен: не найден dzen/tools/cookrate.py")
            break
        mark = "✅" if res.ok else "❌"
        bad += 0 if res.ok else 1
        out.append(f"{mark} {f.name}")
        out += [f"   ❌ {e}" for e in res.errors]
        out += [f"   ⚠️ {w}" for w in res.warns]
    await send_long(message, "\n".join(out))


for alias in ("план", "plan"):
    @router.message(Command(alias))
    async def cmd_plan(message: Message):
        repo: Repo = message.bot.cookrate_repo  # type: ignore[union-attr]
        m = re.search(r"(\d+)", message.text or "")
        await send_long(message, repo.plan(int(m.group(1)) if m else None))


@router.message()
async def fallback(message: Message, state: FSMContext):
    if await state.get_state():
        return  # его съест on_topic
    await message.answer("Меню:", reply_markup=BUTTONS_MENU)
