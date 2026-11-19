#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shorts — сценарный продюсер и монтажер вертикальных роликов (YouTube Shorts / Дзен-ролики).

Формат сценария = обычный markdown со таблицей раскадровки, как в dzen/video/.
Тот же файл читают люди, его же парсит этот инструмент.

    python3 dzen/tools/shorts.py list                       # что есть в dzen/shorts/
    python3 dzen/tools/shorts.py check 004-kurica-v-kofe    # правки по правилам Shorts
    python3 dzen/tools/shorts.py plan  004-kurica-v-kofe    # тайминги + какие кадры нашлись
    python3 dzen/tools/shorts.py subs  004-kurica-v-kofe    # .srt + .ass для вставки субтитров
    python3 dzen/tools/shorts.py voice 004-kurica-v-kofe    # озвучка по планам (нужен edge-tts)
    python3 dzen/tools/shorts.py render 004-kurica-v-kofe --src C:\\shots   # готовый mp4 1080x1920

Зависимости: ffmpeg (обязательно для render), edge-tts (озвучка). Остальное — stdlib.
Монтаж идёт из того, что вы положили в --src: фото и/или короткие видеовставки.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SHORTS = REPO / "dzen" / "shorts"
WORK = Path(__file__).resolve().parent / ".work"

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}

# вертикальное полотно и «мёртвые зоны» интерфейса Shorts
CANVAS_W, CANVAS_H = 1080, 1920
SAFE_TOP, SAFE_BOTTOM = 180, 420          # снизу — плейсхолдер описания и кнопки
SUB_MARGIN_V = 470                        # насколько субтитры подняты от нижнего края
SUB_FONT_SIZE = 62
TITR_FONT_SIZE = 92

RULES = {
    "длительность": (18, 55),
    "планов": (4, 12),
    "хук_сек": 3.0,          # первый план должен уложиться в столько секунд
    "реплика_символов": 92,  # длиннее — не влезает в 2 строки субтитра
    "титр_символов": 28,
    "слов_в_секунду": 2.9,   # темп речи: больше — не успевают прочитать без звука
    "средний_план": (2.8, 6.5),
}

HOOK_WORDS = ("блюдо", "тарелк", "крупно", "макро", "готов", "ложка", "соус", "хруст", "пар", "до/после")


# --- разбор ---------------------------------------------------------------------

def parse_time(cell: str) -> tuple[float, float] | None:
    """`0–4`, `12-24`, `0:04–0:12` → секунды."""
    cell = cell.replace("`", "").strip()
    nums = re.findall(r"(?:\d+:)?\d{1,2}(?:[.,]\d+)?", cell)
    if not nums:
        return None

    def to_sec(tok: str) -> float:
        if ":" in tok:
            m, s = tok.split(":")
            return int(m) * 60 + float(s.replace(",", "."))
        return float(tok.replace(",", "."))

    if len(nums) == 1:
        a = to_sec(nums[0])
        return a, a
    return to_sec(nums[0]), to_sec(nums[1])


@dataclass
class Plan:
    index: int
    start: float
    end: float
    shot: str
    vo: str
    titr: str = ""
    media: Path | None = None
    audio: Path | None = None

    @property
    def length(self) -> float:
        return max(0.6, self.end - self.start)

    @property
    def is_image(self) -> bool:
        return bool(self.media and self.media.suffix.lower() in IMAGE_EXT)

    def strip(self) -> str:
        """Реплика для субтитра: без кавычек-«ёлочек» и эмодзи-украшений."""
        return self.vo.strip().strip("«»\"' ")


@dataclass
class Script:
    path: Path
    title: str
    fm: dict[str, str]
    plans: list[Plan] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.plans[-1].end if self.plans else 0.0

    def words(self) -> int:
        return sum(len(re.findall(r"[\wА-Яа-яЁё-]+", p.strip())) for p in self.plans)


def pick_table(lines: list[str]) -> list[str]:
    """Таблица раскадровки = первая таблица, у которой шапка содержит «Тайм».

    Идём по сырым строкам и останавливаемся на первой строке без `|`: иначе
    справочные таблицы файла («что снимать», «метрики») приклеиваются к раскадровке
    и их строки превращаются в фантомные планы.
    """
    def header(text: str) -> bool:
        cells = [c.strip().lower() for c in text.strip().strip("|").split("|")]
        return any(c in ("тайм", "время", "тайминг", "time") for c in cells)

    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("|") and header(line):
            start = i
            break
    if start is None:                       # шапки нет — берём первую таблицу
        for i, line in enumerate(lines):
            if line.strip().startswith("|"):
                start = i
                break
    if start is None:
        return []
    out = []
    for line in lines[start:]:
        if not line.strip().startswith("|"):
            break
        out.append(line)
    return out


def load(path: Path) -> Script:
    text = path.read_text(encoding="utf-8")
    fm = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith((" ", "-")):
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip().strip('"')
    title = ""
    tm = re.search(r"^#\s+(.+)$", text, re.M)
    if tm:
        title = tm.group(1).strip()

    storyboard = pick_table(text.splitlines())
    plans: list[Plan] = []
    for row in storyboard:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("Тайм", "") or set("".join(cells)) <= set("-: "):
            continue
        span = parse_time(cells[0])
        if not span:
            continue
        start, end = span
        if end <= start:
            end = start + 3.0          # «| 34 |» без конца = план на 3 секунды
        plans.append(Plan(len(plans) + 1, round(start, 2), round(end, 2),
                          cells[1], cells[2], cells[3].strip("«»\"'") if len(cells) > 3 else ""))

    # если в таблице нет таймингов (или они идут «на глаз») — растянуть равномерно
    if plans:
        cur = 0.0
        for p in plans:
            if p.end <= p.start:
                p.end = p.start + 3.0
            if p.start < cur:
                p.start = round(cur, 2)
                p.end = round(max(p.end, p.start + 2.0), 2)
            cur = p.end
    return Script(path, title, fm, plans)


def match_media(script: Script, src: Path | None) -> tuple[list[Path], list[str]]:
    """Кадры: сначала по имени файла в описании плана, потом по порядку."""
    pool: list[Path] = []
    if src and src.exists():
        pool = sorted([p for p in src.iterdir()
                       if p.suffix.lower() in IMAGE_EXT | VIDEO_EXT and not p.name.startswith(".")])
    missing: list[str] = []
    used: set[str] = set()
    for p in script.plans:
        named = re.search(r"([\w\-À-ÿ]+\.(?:jpg|jpeg|png|webp|mp4|mov|webm))", p.shot, re.I)
        if named:
            cand = src / named.group(1) if src else None
            if cand and cand.exists():
                p.media, used = cand, used | {cand.name}
                continue
            missing.append(f"план {p.index}: назван файл {named.group(1)}, его нет в {src}")
            continue
        free = [q for q in pool if q.name not in used]
        if free:
            p.media = free[0]
            used.add(free[0].name)
        else:
            missing.append(f"план {p.index}: свободных файлов не осталось (кадров: {len(pool)})")
    return pool, missing


# --- правила Shorts ---------------------------------------------------------------

def check(script: Script) -> list[tuple[str, str]]:
    """Возвращает [(level, сообщение)]; level: error | warn | ok."""
    out: list[tuple[str, str]] = []
    n = len(script.plans)
    if n == 0:
        return [("error", "таблица раскадровки не найдена — нужен блок `| Тайм | Кадр | За кадром |`")]

    dur = script.duration
    lo, hi = RULES["длительность"]
    if not lo <= dur <= hi:
        out.append(("error" if dur > 61 else "warn",
                    f"длительность {dur:.0f} сек: держим {lo}–{hi}; выше 60 YouTube уже не Shorts"))
    plo, phi = RULES["планов"]
    if not plo <= n <= phi:
        out.append(("warn", f"планов {n}: комфортно {plo}–{phi}"))

    hook = script.plans[0]
    if hook.length > RULES["хук_сек"]:
        out.append(("error", f"хук {hook.length:.1f} сек: первый план должен быть ≤{RULES['хук_сек']} — "
                             "иначе листают дальше"))
    if not any(w.lower() in hook.shot.lower() for w in HOOK_WORDS):
        out.append(("warn", "в первом плане нет готового блюда крупно (макро/тарелка/соус/пар) — "
                            "кадр «процесс» без результата работает хуже"))

    lens = [p.length for p in script.plans]
    avg = sum(lens) / len(lens)
    slo, shi = RULES["средний_план"]
    if not slo <= avg <= shi:
        out.append(("warn", f"средний план {avg:.1f} сек: держим {slo}–{shi}, иначе статика или мельтешение"))

    for p in script.plans:
        if len(p.strip()) > RULES["реплика_символов"]:
            out.append(("error", f"план {p.index}: реплика {len(p.strip())} симв. — "
                                 f"не влезет в 2 строки (макс {RULES['реплика_символов']})"))
        if p.titr and len(p.titr) > RULES["титр_символов"]:
            out.append(("warn", f"план {p.index}: титр {len(p.titr)} симв. — длинноват для вертикали"))

    words = script.words()
    max_words = dur * RULES["слов_в_секунду"]
    if words > max_words:
        out.append(("error", f"слов {words} на {dur:.0f} сек — это {words / dur:.1f} сл/сек, "
                             f"читается тяжело; порог {RULES['слов_в_секунду']}"))

    text_all = " ".join(p.strip() for p in script.plans)
    if not re.search(r"подпис|подпишись|канал|ещё one|сохран", text_all.lower()):
        out.append(("warn", "нет призыва подписаться в закадре: для Shorts это единственная "
                            "метрика, которую алгоритм читает с ваших слов"))
    if not re.search(r"сцен|описан|рецепт|под видео|в закрепе|в коммент", text_all.lower()):
        out.append(("warn", "нет указателя, где рецепт (описание/закреп/комментарий) — "
                            "досмотр без него не конвертируется в переход"))
    loop = script.fm.get("loop", "").lower()
    if loop in ("", "нет", "none"):
        out.append(("warn", "не задан `loop:` в шапке — шортс пересматривают, финал должен "
                            "цепляться за первый кадр словами или смыслом"))
    return out or [("ok", "по правилам Shorts замечаний нет")]


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO))
    except ValueError:
        return str(path.resolve())


# --- субтитры ---------------------------------------------------------------------

def ass_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{int(s):02d}.{int(round((s - int(s)) * 100)):02d}"


def srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"


def wrap(text: str, width: int = 30) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines[:2] if len(lines) <= 2 else lines  # третья строка уже режет кадр


def build_srt(script: Script) -> str:
    blocks = []
    for i, p in enumerate(script.plans, 1):
        if not p.strip():
            continue
        blocks.append(f"{i}\n{srt_time(p.start)} --> {srt_time(p.end)}\n" +
                      "\n".join(wrap(p.strip(), 32)) + "\n")
    return "\n".join(blocks)


def build_ass(script: Script, plans: list[Plan] | None = None) -> str:
    """.ass с жёсткими отступами под интерфейс Shorts: текст не залезает под кнопки."""
    items = plans or script.plans
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {CANVAS_W}
PlayResY: {CANVAS_H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{SUB_FONT_SIZE},&H00FFFFFF,&H00101010,&H88000000,-1,0,0,0,100,100,0.6,0,1,3.2,1.2,2,64,64,{SUB_MARGIN_V},1
Style: Titr,Arial,{TITR_FONT_SIZE},&H002BA6F4,&H00101010,&H88000000,-1,0,0,0,100,100,1.2,0,1,4.0,1.6,8,64,64,{SAFE_TOP},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    for p in items:
        if p.strip():
            txt = "\\N".join(wrap(p.strip(), 30))
            ev.append(f"Dialogue: 0,{ass_time(p.start)},{ass_time(p.end)},Default,,0,0,0,,{{\\fad(90,110)}}{txt}")
        if p.titr:
            ev.append(f"Dialogue: 1,{ass_time(p.start)},{ass_time(min(p.end, p.start + 2.2))},Titr,,0,0,0,,{{\\fad(60,120)}}{p.titr.upper()}")
    return head + "\n".join(ev) + "\n"


# --- рендер -----------------------------------------------------------------------

def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode("utf-8", "ignore")[-1200:]


def ffprobe_duration(path: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    code, out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", path])
    try:
        return float(out.strip().splitlines()[-1]) if not code else None
    except ValueError:
        return None


def ensure_font(dest: Path) -> str | None:
    """Кладём шрифт рядом с рендером: на Windows пути с двоеточием в drawtext — боль,
    относительный путь работает стабильно в обеих ОС."""
    for cand in (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                 "/Library/Fonts/Arial Bold.ttf",
                 "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        p = Path(cand)
        if p.exists():
            out = dest / p.name
            if not out.exists():
                shutil.copy(p, out)
            return out.name
    return None


async def tts_line(text: str, out: Path, voice: str) -> bool:
    if not text:
        return False
    try:
        import edge_tts  # type: ignore
    except ImportError:
        return False
    await edge_tts.Communicate(text, voice, rate="+6%").save(str(out))
    return out.exists() and out.stat().st_size > 900


async def retime_by_voice(script: Script, dest: Path, voice: str) -> tuple[list[Plan], bool]:
    """Озвучиваем по планам и растягиваем тайминги под реплику — так ролик не «спешит»."""
    plans: list[Plan] = []
    cur = 0.0
    got_any = False
    for p in script.plans:
        np = Plan(p.index, 0, 0, p.shot, p.vo, p.titr, p.media)
        mp3 = dest / f"vo-{p.index:02d}.mp3"
        if await tts_line(p.strip(), mp3, voice):
            d = ffprobe_duration(mp3) or (len(p.strip()) / 15.0)
            np.audio = mp3
            got_any = True
        else:
            d = p.length
        np.start, np.end = round(cur, 2), round(cur + max(1.6, d + 0.30), 2)
        cur = np.end
        plans.append(np)
    return plans, got_any


def render_segment(p: Plan, out: Path, work: Path, *, ass: Path | None, font: str | None,
                   audio: Path | None, fps: int, kenburns: bool) -> tuple[bool, str]:
    if not p.media:
        return False, f"план {p.index}: нет файла — положите кадр в --src"
    filters = [
        f"scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase",
        f"crop={CANVAS_W}:{CANVAS_H}",
        f"setsar=1,fps={fps}",
    ]
    if kenburns and p.is_image:
        frames = max(24, int(p.length * fps))
        zoom = min(0.06 / frames, 0.004)
        filters = [f"scale={CANVAS_W * 2}:{CANVAS_H * 2}:force_original_aspect_ratio=increase",
                   f"crop={CANVAS_W}:{CANVAS_H}",
                   f"zoompan=z='min(zoom+{zoom:.5f},1.06)':d={frames}:s={CANVAS_W}x{CANVAS_H}:fps={fps}"]
    if ass:
        filters.append(f"ass={ass.name}")
    vf = ",".join(filters)

    cmd = ["ffmpeg", "-y"]
    if p.is_image:
        cmd += ["-loop", "1", "-t", f"{p.length:.2f}"]
    cmd += ["-i", p.media.name]
    if audio:
        cmd += ["-i", audio.name, "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2"]
    cmd += ["-vf", vf, "-t", f"{p.length:.2f}", "-pix_fmt", "yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(fps), out.name]
    code, log = run(cmd, cwd=work)
    if code:
        return False, f"план {p.index}: ffmpeg, {log[-320:]}"
    return out.exists(), "" if out.exists() else f"план {p.index}: файл не создан"


def cmd_list(args) -> int:
    if not SHORTS.exists():
        print("папки dzen/shorts/ нет")
        return 1
    files = sorted(SHORTS.glob("*.md"))
    print(f"сценариев: {len(files)}\n")
    for f in files:
        if f.name.lower().startswith("readme"):
            continue
        sc = load(f)
        verdict = check(sc)
        bad = sum(1 for lvl, _ in verdict if lvl == "error")
        warn = sum(1 for lvl, _ in verdict if lvl == "warn")
        mark = "❌" if bad else ("⚠" if warn else "✅")
        print(f"{mark} {f.stem:<28} {sc.duration:>5.0f} сек · {len(sc.plans):>2} план(ов) · "
              f"ошибок {bad}, замечаний {warn}   {sc.fm.get('topic', sc.title)[:40]}")
    print("\n`check <имя>` — что править, `render <имя> --src <папка>` — собрать mp4")
    return 0


def cmd_check(args) -> int:
    path = find_script(args.name)
    sc = load(path)
    print(f"# {path.stem}")
    bad = 0
    for level, msg in check(sc):
        icon = {"error": "❌", "warn": "⚠", "ok": "✅"}[level]
        print(f"  {icon} {msg}")
        bad += level == "error"
    print(f"\nитого: {sc.duration:.0f} сек, {len(sc.plans)} планов, "
          f"{sc.words()} слов, темп {sc.words() / max(1, sc.duration):.1f} сл/сек")
    return 1 if bad else 0


def cmd_plan(args) -> int:
    path = find_script(args.name)
    sc = load(path)
    src = Path(args.src) if args.src else None
    pool, missing = match_media(sc, src)
    print(f"{'план':<5} {'старт':>6} {'длит':>6}  {'кадр-файл':<24} реплика")
    for p in sc.plans:
        media = p.media.name if p.media else "—"
        print(f"{p.index:<5} {p.start:>6.2f} {p.length:>6.2f}  {media:<24} {p.strip()[:44]}")
    print(f"\nдоступных файлов в {src or 'не задано'}: {len(pool)}")
    for m in missing:
        print(f"  ⚠ {m}")
    if args.retime:
        plans, ok = asyncio.run(retime_by_voice(sc, WORK, args.voice))
        WORK.mkdir(parents=True, exist_ok=True)
        print("\nтайминги по длине озвучки" + ("" if ok else " (edge-tts недоступен → как в таблице):"))
        for p in sc.plans:
            np = plans[p.index - 1]
            print(f"  план {np.index}: {np.start:6.2f} → {np.end:6.2f}  ({np.length:.2f} сек)")
    return 0


def cmd_subs(args) -> int:
    path = find_script(args.name)
    sc = load(path)
    out_dir = Path(args.out) if args.out else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir = out_dir.resolve()
    srt = out_dir / f"{path.stem}.srt"
    ass = out_dir / f"{path.stem}.ass"
    srt.write_text(build_srt(sc), encoding="utf-8")
    ass.write_text(build_ass(sc), encoding="utf-8")
    print(f"srt → {rel(srt)}  (загрузить субтитром в YouTube Studio)")
    print(f"ass → {rel(ass)}  (вжигается в кадр, всегда читается)")
    n = len([p for p in sc.plans if p.strip()])
    print(f"реплик: {n}")
    return 0


def cmd_voice(args) -> int:
    path = find_script(args.name)
    sc = load(path)
    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / f"{path.stem}-voice.mp3"

    async def go() -> bool:
        try:
            import edge_tts  # type: ignore
        except ImportError:
            print("edge-tts не установлен:  pip install edge-tts")
            return False
        text = " ".join(p.strip() for p in sc.plans if p.strip())
        await edge_tts.Communicate(text, args.voice, rate="+6%").save(str(out))
        return out.exists()

    if asyncio.run(go()):
        print(f"озвучка целиком → {out}  ({ffprobe_duration(out) or 0:.1f} сек)")
        print("для монтажа по планам (каждая реплика отдельно) — `render`: он озвучивает сам")
        return 0
    return 1


def cmd_render(args) -> int:
    if not shutil.which("ffmpeg"):
        print("ffmpeg не найден — монтировать нечем.\n"
              "  Windows:  winget install Gyan.FFmpeg      (потом открыть НОВОЕ окно cmd)\n"
              "  macOS:    brew install ffmpeg\n"
              "  Ubuntu:   sudo apt install ffmpeg fonts-dejavu-core")
        return 1
    path = find_script(args.name)
    sc = load(path)
    work = Path(args.out) if args.out else (WORK / path.stem)
    work.mkdir(parents=True, exist_ok=True)

    src = Path(args.src) if args.src else None
    if not src or not src.exists():
        print(f"--src не задан или пуст: {src}\nПоложите кадры (jpg/png/mp4) в папку и укажите её: "
              f"render {path.stem} --src C:\\shots")
        return 1
    _, missing = match_media(sc, src)
    if all(p.media is None for p in sc.plans):
        print("в --src нет ни одного подходящего файла")
        return 1

    font = ensure_font(work)
    plans = sc.plans
    voice_on = not args.no_voice
    if voice_on:
        plans, ok = asyncio.run(retime_by_voice(sc, work, args.voice))
        print("озвучка по планам: " + ("готова, тайминги пересчитаны под реплики"
                                       if ok else "нет edge-tts → монтах по таймингам таблицы"))
        if not ok:
            plans = sc.plans
    ass_path = work / "subs.ass"
    ass_path.write_text(build_ass(Script(path, sc.title, sc.fm, plans)), encoding="utf-8")
    if font:
        print(f"шрифт: {font}")

    fps = int(args.fps)
    segs: list[Path] = []
    for p in plans:
        seg = work / f"seg-{p.index:02d}.mp4"
        ok, err = render_segment(p, seg, work, ass=ass_path, font=font,
                                 audio=p.audio if voice_on else None, fps=fps,
                                 kenburns=not args.static)
        if not ok:
            print(err)
            return 1
        segs.append(seg)

    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in segs), encoding="utf-8")
    final = work / f"{path.stem}.mp4"
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst.name]
    if not voice_on:
        cmd += ["-an"]
    cmd += ["-c", "copy", final.name]
    code, log = run(cmd, cwd=work)
    if code:
        print("склейка не удалась: " + log[-400:])
        return 1

    dur = ffprobe_duration(final) or sum(p.length for p in plans)
    print(f"\n✅ {final}  ·  {dur:.1f} сек · {len(segs)} план(ов) · {CANVAS_W}x{CANVAS_H}")
    print("проверьте первые 2 секунды на телефоне: там решается досмотр")
    for m in missing:
        print(f"  ⚠ {m}")
    if args.report:
        for level, msg in check(Script(path, sc.title, sc.fm, plans)):
            print(f"  {'❌' if level == 'error' else ('⚠' if level == 'warn' else '✅')} {msg}")
    return 0


def find_script(name: str) -> Path:
    p = Path(name)
    if p.exists():
        return p
    if not p.suffix:
        p = p.with_suffix(".md")
    for cand in (SHORTS / p.name, SHORTS / name, REPO / name):
        if cand.exists():
            return cand
    hits = list(SHORTS.glob(f"*{Path(name).stem}*"))
    if hits:
        return hits[0]
    print(f"сценарий не найден: {name}. Есть: " +
          ", ".join(f.stem for f in sorted(SHORTS.glob('*.md'))) )
    sys.exit(2)


def main() -> int:
    p = argparse.ArgumentParser(prog="shorts", description="сценарии и монтаж вертикальных роликов")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, func in (("list", cmd_list), ("stats", cmd_list)):
        s = sub.add_parser(name)
        s.set_defaults(func=func)

    for name, func in (("check", cmd_check), ("subs", cmd_subs), ("voice", cmd_voice)):
        s = sub.add_parser(name)
        s.add_argument("name")
        if name == "subs":
            s.add_argument("--out", default=None)
        if name == "voice":
            s.add_argument("--voice", default="ru-RU-SvetlanaNeural")
        s.set_defaults(func=func)

    pl = sub.add_parser("plan")
    pl.add_argument("name")
    pl.add_argument("--src", default=None)
    pl.add_argument("--retime", action="store_true", help="пересчитать тайминги под озвучку")
    pl.add_argument("--voice", default="ru-RU-SvetlanaNeural")
    pl.set_defaults(func=cmd_plan)

    rn = sub.add_parser("render")
    rn.add_argument("name")
    rn.add_argument("--src", required=True, help="папка с фото/видео для планов")
    rn.add_argument("--out", default=None)
    rn.add_argument("--fps", default="30")
    rn.add_argument("--voice", default="ru-RU-SvetlanaNeural")
    rn.add_argument("--no-voice", action="store_true", help="без озвучки: только субтитры")
    rn.add_argument("--static", action="store_true", help="без наезда камеры (Ken Burns)")
    rn.add_argument("--report", action="store_true", help="после сборки — отчёт по правилам")
    rn.set_defaults(func=cmd_render)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
