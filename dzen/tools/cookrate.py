#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cookrate — помощник канала COOKRATE «Необычная Кухня».

Проверяет тексты по чек-листу dzen/checklist.md, заводит новые публикации,
показывает план и статистику. Только stdlib, зависимостей нет.

    python3 dzen/tools/cookrate.py check [путь]
    python3 dzen/tools/cookrate.py new 007 grusha-v-teste --rubric article --date 2026-11-30
    python3 dzen/tools/cookrate.py plan [--week 2]
    python3 dzen/tools/cookrate.py stats
    python3 dzen/tools/cookrate.py next
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
DZEN = REPO / "dzen"
PLAN = DZEN / "content-plan.md"

# --- правила -----------------------------------------------------------------

REQUIRED_YAML = ("number", "type", "status")

# слова, за которыми канал перестаёт быть собой
FORBIDDEN = [
    "шедевр", "невероятн", "бомба", "просто вау", "коктейль вкуса",
    "детокс", "похуден", "пп-рецепт", "правильное питание",
    "в этой статье", "вы не знали", "вы не представляете", "шок", "вы когда-нибудь слышали",
]

# обязательные блоки публикаций-рецептов
BLOCKS = {
    "products": r"^##+\s*(Что нужно|Продукты)",
    "steps": r"^##+\s*(Пошагово|Порядок)",
    "why": r"Почему[^.\n]{0,25}работает",
    "substitute": r"(^##+\s*Если |чем заменить|заменит)",
    "errors": r"(Так не делайте|не делай)",
}

ALLOWED_LATIN = {
    "cookrate", "readme", "slug", "draft", "ready", "published", "type", "status",
    "number", "video", "reconstructed", "length", "price", "date", "rubric", "pub",
    "reference", "updated", "duration", "python", "markdown", "git", "grep", "bash",
    "png", "jpg", "jpeg", "html", "http", "https", "www", "dzen", "rutube", "yandex",
    "anton", "oswald", "bebas", "sans", "serif", "px", "pt", "dpi", "api", "url",
    "cto", "yaml", "json", "regex", "utf", "min", "max", "ok", "id", "im", "vs",
    "speckled", "matte", "apron", "linen", "bun", "face", "light", "kitchen", "woman",
    "the", "with", "from", "both", "hands", "chest", "height", "tile", "small",
}

READING_SIGNS_PER_MIN = 1300  # спокойное чтение рецептов с промоткой

# --- разбор файла -------------------------------------------------------------

FM_RE = re.compile(r"^---\s*\n(?P<fm>.*?)\n---\s*\n?(?P<body>.*)$", re.S)


def parse(path: pathlib.Path):
    text = path.read_text(encoding="utf-8")
    m = FM_RE.match(text)
    if not m:
        return {}, text, False
    fm = {}
    for line in m.group("fm").splitlines():
        if ":" in line and not line.startswith((" ", "-")):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm, m.group("body"), True


def kind_of(fm: dict) -> str:
    t = (fm.get("type") or "").lower()
    if "welcome" in t:
        return "welcome"
    if "video" in t and "post" not in t and "article" not in t:
        return "video"
    if "post" in t:
        return "post"
    if "article" in t:
        return "article"
    return "other"


def plural(n: int, one: str, few: str, many: str) -> str:
    n100, n10 = n % 100, n % 10
    if 11 <= n100 <= 14:
        return many
    if n10 == 1:
        return one
    if 2 <= n10 <= 4:
        return few
    return many


def strip_noise(body: str) -> str:
    body = re.sub(r"```.*?```", "", body, flags=re.S)      # fenced code
    body = re.sub(r"`[^`\n]*`", " ", body)                   # inline code
    body = re.sub(r"https?://\S+", " ", body)                # urls
    body = re.sub(r"^\s*\|[-\s:|]+\|\s*$", "", body, flags=re.M)  # table rules
    return body


def title_of(body: str) -> str:
    m = re.search(r"^#\s+(.+)$", body, re.M)
    return m.group(1).strip() if m else ""


def body_no_title(body: str) -> str:
    return re.sub(r"^#\s+.+$", "", body, count=1, flags=re.M)


# --- проверки -----------------------------------------------------------------

class Report:
    def __init__(self, path: str):
        self.path = path
        self.errors: list[str] = []
        self.warns: list[str] = []

    def err(self, msg: str):
        self.errors.append(msg)

    def warn(self, msg: str):
        self.warns.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def check_file(path: pathlib.Path, root: pathlib.Path) -> Report | None:
    fm, body, has_fm = parse(path)
    rel = path.relative_to(root).as_posix()
    if not has_fm or "number" not in fm:
        return None  # не публикация — не линтуем
    rep = Report(rel)
    kind = kind_of(fm)
    archived = fm.get("status") == "published"

    def note(msg: str, hard: bool = True):
        """Ошибка публикации — ошибка; замечание к архиву — предупреждение."""
        (rep.err if (hard and not archived) else rep.warn)(
            msg if not archived else msg + " [архив: сверить с эфиром, не править]")
    plain = strip_noise(body)
    title = title_of(body)
    body_chars = len(body_no_title(plain).replace("\n", "").replace(" ", ""))

    # шапка
    for key in REQUIRED_YAML:
        if key not in fm:
            rep.err(f"в YAML-шапке нет поля `{key}`")
    if fm.get("status") not in ("draft", "ready", "published"):
        rep.err(f"статус `{fm.get('status')}` вне draft/ready/published")
    if "rubric" not in fm and kind in ("article", "post"):
        rep.warn("нет поля `rubric` — рубрика должна быть у каждой публикации")

    # заголовок
    if not title:
        rep.err("нет заголовка `# …`")
    else:
        n = len(title)
        if not 45 <= n <= 60:
            (rep.err if n < 25 or n > 85 else rep.warn)(
                f"заголовок {n} симв., надо 45–60")

    # длина
    if kind in ("article",):
        if not 1800 <= body_chars <= 4000:
            rep.warn(f"объём {body_chars} знаков: для статьи-разбора цель 2500–3500")
    elif kind in ("post", "welcome"):
        if body_chars < 700:
            note(f"объём {body_chars} знаков: коротковато, цель 800–1200", hard=False)
        elif body_chars > 1900:
            note(f"объём {body_chars} знаков: пост распух, держим до ~1500", hard=False)

    if kind in ("article", "post"):
        for name, pat in BLOCKS.items():
            if not re.search(pat, plain, re.M | re.I):
                note(f"нет блока «{name}» ({BLOCKS_HINT[name]})")

        # цифры вместо «по вкусу»
        if "₽" not in plain:
            note("нет цены порции — в каждом тексте должен быть знак ₽")
        if not re.search(r"\d+\s*(мин|минут)", plain):
            note("нет времени приготовления в минутах")
        bakes = re.search(r"духовк|грил|запеч", plain, re.I)
        if bakes and "°C" not in plain and not re.search(r"\d{3}\s*°", plain):
            note("блюдо идёт в духовку, но режима нагрева нет — указать °C")

        # CTA: вопрос или прямая просьба написать в комментариях
        tail = plain.rstrip()[-500:]
        if not re.search(r"[?]|напиш|комментар|спрос|спорим", tail, re.I):
            note("в конце нет вопроса читателю — CTA отсутствует")
        if "Моё" not in plain and "сохран" not in plain.lower():
            note("нет призыва сохранить в «Моё» — для рецептов это главная метрика", hard=False)

        # теги
        tags = re.findall(r"(?<![\w/])#[\wА-Яа-яЁё]+", plain)
        if not 3 <= len(tags) <= 7:
            note(f"тегов {len(tags)}: держим 4–6", hard=False)
        if "#cookrate" not in plain:
            note("нет брендового тега #cookrate")

        # «почему работает» должен быть объяснением, а не отпиской
        m = re.search(BLOCKS["why"], plain, re.I)
        if m:
            block = plain[m.start(): m.start() + 700]
            block = re.split(r"\n##", block)[0]
            if len(block.replace("\n", " ").strip()) < 180:
                rep.warn("блок «почему работает» тоньше 3–5 строк — это фирменное, не сокращать")

    if kind == "video":
        rows = len([l for l in plain.splitlines() if l.strip().startswith("|")])
        if rows < 8:
            rep.warn(f"в раскадровке {rows} табличных строк: для 45–75 сек нужно 7–9 планов")
        if "0–4" not in plain:
            rep.err("нет крючка на 0–4 секунде — ролик без готового блюда в начале не смотрят")

    # запрещённые слова
    low = plain.lower()
    for word in FORBIDDEN:
        # короткое слово ищем отдельным словом: «шок» не должен ловить «шоколад»
        pat = rf"(?<![а-яёa-z]){re.escape(word)}(?![а-яёa-z])" if len(word) <= 5 else re.escape(word)
        if re.search(pat, low):
            rep.err(f"запрещённое слово «{word}» — см. «Что мы не делаем» в channel.md")

    # случайная латиница в русском тексте
    leaks = set()
    for w in re.findall(r"[A-Za-z][A-Za-z\-']{4,}", plain):
        if w.lower() not in ALLOWED_LATIN:
            leaks.add(w)
    # в видео-шаблоне промпта латиница допустима — снимаем строки из blockquote
    if leaks and kind != "video":
        rep.warn("латиница в тексте: " + ", ".join(sorted(leaks)) + " — перевести или убрать")

    return rep


BLOCKS_HINT = {
    "products": "«Продукты»/«Что нужно» с граммами и ценой блюда",
    "steps": "«Пошагово»/«Порядок»: шаг = глагол + срок",
    "why": "«Почему работает» — разбор вкуса, 3–5 строк",
    "substitute": "«Если нет X» / чем заменить",
    "errors": "«Так не делайте» — 2–3 запрета",
}


# --- команды -------------------------------------------------------------------

def cmd_check(args) -> int:
    root = DZEN
    target = pathlib.Path(args.path) if args.path else DZEN
    if target.is_file():
        files = [target]
    else:
        files = sorted(target.rglob("*.md"))
    reports = []
    skipped = 0
    for f in files:
        rep = check_file(f, REPO if f.is_relative_to(DZEN) else f.parents[0])
        if rep is None:
            skipped += 1
            continue
        reports.append(rep)

    if not reports:
        print("публикаций для проверки не найдено")
        return 0
    failed = 0
    for rep in reports:
        if rep.ok and not rep.warns:
            print(f"✓ {rep.path}")
            continue
        mark = "✗" if rep.errors else "⚠"
        print(f"{mark} {rep.path}")
        for e in rep.errors:
            print(f"    ✗ {e}")
        for w in rep.warns:
            print(f"    ⚠ {w}")
        if rep.errors:
            failed += 1
    print(f"\nпроверено {len(reports)} "
          f"{plural(len(reports), 'публикация', 'публикации', 'публикаций')}, "
          f"{skipped} "
          f"{plural(skipped, 'служебный файл пропущен', 'служебных файла пропущено', 'служебных файлов пропущено')}")
    if failed:
        print(f"ошибок: {failed} "
              f"{plural(failed, 'файл', 'файла', 'файлов')} — править перед публикацией")
        print("подсказка: `check <файл>` по одному файлу, `new` — завести следующий слот плана")
    return 1 if failed else 0


ARTICLE_TPL = """---
number: {num}
type: article
rubric: "{rubric}"
date: {date}
status: draft
length: ~2800 знаков
price: ~___ ₽/порция
---

# {title}

Сомнение читателя в двух строках и обещание его закрыть. Не «в этой статье вы узнаете».

## Продукты (4 порции, ~___ ₽ за порцию)

* Основной продукт — 000 г
* Тот самый необычный — 000 г
* Соль, жир, кислота, горечь — по строчке на каждый

## Пошагово

1. **Подготовка.** Один шаг = один глагол + срок.
2. **Тепло.** Температура и минуты.
3. **Соус.** Что и в каком порядке.
4. **Отдых.** Что дать постоять и зачем.

## Почему работает

Три-пять строк про вкус: соль + жир + сахар + кислота. Почему именно так,
а не «просто вкусно».

## Если нет ___

Чем заменить, чтобы рецепт не развалился. Два-три варианта с поправкой пропорций.

## Так не делайте

1. Запрет с причиной.
2. Запрет с причиной.
3. Запрет с причиной.

## Подача и хранение

С чем подавать, сколько живёт, как разогревать, что не замораживать.

**Вопрос читателю на одно слово в ответе.**

#рецепты #cookrate #необычнаякухня
"""

POST_TPL = """---
number: {num}
type: post
rubric: "{rubric}"
date: {date}
status: draft
length: ~1000 знаков
price: ~___ ₽/порция
---

# {title}

Один рецепт, одна эмоция, без лирики. Заголовок сразу про результат.

## Что нужно

* Продукты с граммами

## Порядок

1. Шаг — глагол + срок.
2. Шаг.
3. Шаг.

## Почему работает

Три-пять строк про контраст вкусов.

## Так не делайте

1. Запрет.
2. Запрет.

**Одна практическая ремарка для тех, кто боится сочетания.**

#рецепты #cookrate #необычнаякухня
"""

VIDEO_TPL = """---
number: {num}
type: video-script
pub: ../published/{num}-{slug}.md
duration: ~60 сек
status: draft
---

# Ролик №{num} — «{title}», 60 секунд

## Тайминг

| Тайм | Кадр | Текст за кадром |
|---|---|---|
| 0–4 | Готовое блюдо крупно | Крючок-возражение читателя |
| 4–14 | Руки, продукт | Одна операция |
| 14–30 | Огонь/духовка, звук еды | Одно правило |
| 30–45 | Соус, полив | Цена порции титром |
| 45–60 | Тарелка, финальный полив | «Сохраняйте в “Моё”» |

## Правила съёмки

* План не дольше 4 секунд, звук еды не глушить музыкой.
* Субтитры обязательны, шрифт тот же, что на обложке.
* Превью — Анжела по шаблону dzen/angela.md, подпись капсом в «ёлочках».
"""

TEMPLATES = {"article": ARTICLE_TPL, "post": POST_TPL, "video": VIDEO_TPL}
RUBRICS = {
    "article": "🔪 Неожиданное сочетание",
    "post": "💸 Необычно, но дёшево",
    "video": "✨ На эффект",
}


def cmd_new(args) -> int:
    num = re.sub(r"\D", "", args.number)
    if not num:
        print("номер должен содержать цифры: 7 или 007")
        return 1
    num = num.zfill(3)
    if not re.fullmatch(r"[a-z0-9-]+", args.slug):
        print("slug — только строчные латиница, цифры и дефис (правило №7 в AGENTS.md)")
        return 1
    template = TEMPLATES[args.rubric]
    date = args.date or dt.date.today().isoformat()
    title = args.title or args.slug.replace("-", " ").capitalize()
    fname = f"{num}-{args.slug}.md"
    dest = DZEN / "next" / fname
    if dest.exists() and not args.force:
        print(f"{dest.relative_to(REPO)} уже существует (--force перезапишет)")
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        template.format(num=num, slug=args.slug, date=date, title=title,
                        rubric=args.rubric_name or RUBRICS[args.rubric]),
        encoding="utf-8")
    print(f"создан {dest.relative_to(REPO)}")
    print("черновик по каркасу — наполнить, затем: python3 dzen/tools/cookrate.py check")
    return 0


def cmd_plan(args) -> int:
    if not PLAN.exists():
        print(f"нет файла {PLAN.relative_to(REPO)}")
        return 1
    week = None
    current = ""
    rows = []
    for line in PLAN.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##+\s*(Неделя\s*(\d+)[^\n]*)", line)
        if m:
            current = m.group(1).strip()
            continue
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("Дата", "") or set(cells[0]) <= set("-: "):
            continue
        rows.append((current, cells))
    shown = 0
    for section, cells in rows:
        wm = re.search(r"Неделя\s*(\d+)", section)
        if args.week and (not wm or int(wm.group(1)) != args.week):
            continue
        shown += 1
        date, rubric, topic = cells[0], cells[1], cells[2]
        status = cells[-1] if "next/" in cells[-1] or "ready" in cells[-1] else ""
        print(f"{date:<12} {rubric:<8} {topic}")
        if status:
            print(f"{'':<12} → {status}")
    if not shown:
        print("в планe нет строк для такой недели")
        return 1
    head = f"Неделя {args.week}" if args.week else "Все недели"
    print(f"\n{head}: {shown} слот(ов). Свободные слоты закрываются командой `new`.")
    return 0


def cmd_stats(args) -> int:
    files = sorted((DZEN / "published").glob("*.md")) + sorted((DZEN / "next").glob("*.md"))
    if not files:
        print("нет публикаций")
        return 1
    print(f"{'файл':<44} {'тип':<9} {'знаков':>7} {'чтение':>7}  статус")
    for f in files:
        fm, body, _ = parse(f)
        chars = len(body_no_title(strip_noise(body)).replace("\n", "").replace(" ", ""))
        mins = max(1, round(chars / READING_SIGNS_PER_MIN))
        typ = kind_of(fm)
        print(f"{f.relative_to(REPO).as_posix():<44} {typ:<9} {chars:>7} {str(mins) + ' мин':>7}  "
              f"{fm.get('status', '—')}{' (реконструкция)' if fm.get('reconstructed') == 'true' else ''}")
    print(f"\nвсего файлов: {len(files)}")
    return 0


def cmd_next(args) -> int:
    files = sorted((DZEN / "next").glob("*.md"))
    if not files:
        print("next/ пуст — неделя закрыта, берите слот из `plan`")
        return 0
    print("готово к публикации (можно копировать в Дзен как есть):\n")
    for f in files:
        fm, body, _ = parse(f)
        title = title_of(body)
        mark = "✓" if fm.get("status") == "ready" else "•"
        print(f"  {mark} {f.name:<32} {fm.get('date', '')}  {title}")
    print("\nпубликуем сами и только руками пользователя — см. правило №1 в AGENTS.md")
    return 0


# --- CLI -----------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(prog="cookrate", description="помощник канала COOKRATE")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="линт текстов по чек-листу")
    c.add_argument("path", nargs="?", default=str(DZEN))
    c.set_defaults(func=cmd_check)

    n = sub.add_parser("new", help="завести новый текст по каркасу")
    n.add_argument("number", help="номер публикации: 7 или 007")
    n.add_argument("slug", help="ascii-slug имени файла")
    n.add_argument("--rubric", choices=list(TEMPLATES), default="article")
    n.add_argument("--rubric-name", dest="rubric_name", default=None,
                   help="своя подпись рубрики в YAML")
    n.add_argument("--date", default=None)
    n.add_argument("--title", default=None)
    n.add_argument("--force", action="store_true")
    n.set_defaults(func=cmd_new)

    pl = sub.add_parser("plan", help="что выходит по контент-плану")
    pl.add_argument("--week", type=int, default=None)
    pl.set_defaults(func=cmd_plan)

    st = sub.add_parser("stats", help="длина, время чтения, статусы")
    st.set_defaults(func=cmd_stats)

    nx = sub.add_parser("next", help="готовые тексты недели")
    nx.set_defaults(func=cmd_next)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
