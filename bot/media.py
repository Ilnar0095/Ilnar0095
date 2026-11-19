"""Медиа: иллюстрации, обложки, ролики, озвучка.

Принцип тот же, что у текстов: если внешнего ИИ-провайдера нет, берём то, что уже
есть в репозитории (референс Анжелы) и собираем кадр средствами ffmpeg. Бот никогда
не «молча пропускает» шаг: вместо результата возвращает строку `hint`, и хендлер
её показывает.

ffmpeg/ffprobe ищутся в PATH. Их отсутствие — не ошибка бота, а отсутствующая
возможность, о которой сказано прямо.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import shutil
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp

FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]


@dataclass
class MediaResult:
    files: list[Path] = field(default_factory=list)
    hint: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.files)


def which(tool: str) -> str | None:
    return shutil.which(tool)


def find_font(cfg) -> str | None:
    if cfg.cover_font and Path(cfg.cover_font).exists():
        return cfg.cover_font
    for f in FONTS:
        if Path(f).exists():
            return f
    return None


async def _run(*cmd: str, cwd: Path | None = None) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode("utf-8", "ignore")[-1500:]


async def _download(url: str, dest: Path) -> bool:
    timeout = aiohttp.ClientTimeout(total=180)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url) as r:
            if r.status >= 400:
                return False
            dest.write_bytes(await r.read())
    return True


# --- репликация: картинки и видео ------------------------------------------------

async def _replicate(cfg, model: str, inp: dict, poll_sec: int = 300) -> list[str]:
    """POST /v1/predictions с poll=true, fallback на обычный create + poll."""
    headers = {"Authorization": f"Token {cfg.replicate_token}",
               "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=poll_sec + 60)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post("https://api.replicate.com/v1/predictions",
                          json={"version": model, "input": inp}, headers=headers) as r:
            raw = await r.text()
            if r.status >= 400:
                raise RuntimeError(f"replicate {r.status}: {raw[:300]}")
            data = json.loads(raw)
        # если вернули pending — ждём
        started = time.time()
        while data.get("status") not in ("succeeded", "failed", "canceled") and time.time() - started < poll_sec:
            await asyncio.sleep(4)
            url = (data.get("urls") or {}).get("get")
            if not url:
                break
            async with s.get(url, headers=headers) as r:
                data = json.loads(await r.text())
        out = data.get("output") or []
        if isinstance(out, str):
            out = [out]
        if data.get("status") != "succeeded":
            raise RuntimeError(f"replicate: {data.get('status')}: {str(data.get('error'))[:200]}")
        return [u for u in out if isinstance(u, str)]


async def ai_images(cfg, prompts: list[str], dest: Path) -> MediaResult:
    """Кадры по промптам. none-провайдер → пустой результат с подсказкой."""
    dest.mkdir(parents=True, exist_ok=True)
    if cfg.image_provider == "none" or not prompts:
        return MediaResult(hint="IMAGE_PROVIDER=none: включите openai или replicate в bot/.env")

    files: list[Path] = []
    try:
        if cfg.image_provider == "openai":
            timeout = aiohttp.ClientTimeout(total=300)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                for i, prompt in enumerate(prompts, 1):
                    async with s.post(
                        cfg.llm_base.rstrip("/") + "/images/generations",
                        headers={"Authorization": f"Bearer {cfg.llm_key}"},
                        json={"model": "gpt-image-1", "prompt": prompt,
                              "size": cfg.image_size, "n": 1}) as r:
                        raw = await r.text()
                        if r.status >= 400:
                            raise RuntimeError(f"images {r.status}: {raw[:300]}")
                        item = json.loads(raw)["data"][0]
                        out = dest / f"shot-{i}.png"
                        if item.get("b64_json"):
                            out.write_bytes(base64.b64decode(item["b64_json"]))
                        elif item.get("url"):
                            if not await _download(item["url"], out):
                                continue
                        else:
                            continue
                        files.append(out)
            return MediaResult(files)
        if cfg.image_provider == "replicate":
            for i, prompt in enumerate(prompts, 1):
                urls = await _replicate(cfg, cfg.image_model,
                                        {"prompt": prompt, "aspect_ratio": "16:9"})
                out = dest / f"shot-{i}.png"
                if urls and await _download(urls[0], out):
                    files.append(out)
            return MediaResult(files)
    except Exception as exc:  # сеть/ключ/лимиты — объясняем пользователю, не падаем
        return MediaResult(files, hint=f"генерация не удалась: {str(exc)[:300]}")
    return MediaResult(hint="неизвестный IMAGE_PROVIDER")


async def ai_video(cfg, prompt: str, dest: Path) -> MediaResult:
    dest.mkdir(parents=True, exist_ok=True)
    if cfg.video_provider == "none":
        return MediaResult(hint="VIDEO_PROVIDER=none: включите replicate в bot/.env "
                                "или попросите тизер из кадров (ffmpeg)")
    try:
        urls = await _replicate(cfg, cfg.video_model,
                                {"prompt": prompt, "seconds": cfg.video_seconds}, poll_sec=600)
        out = dest / "teaser.mp4"
        if urls and await _download(urls[-1], out):
            return MediaResult([out])
        return MediaResult(hint="модель вернула пустой вывод")
    except Exception as exc:
        return MediaResult(hint=f"видео не получилось: {str(exc)[:300]}")


# --- обложка и тизер средствами ffmpeg -----------------------------------------

def caption_from(text: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    title = m.group(1).strip() if m else "COOKRATE"
    title = re.split(r"[:—–\.]", title)[0].strip()
    title = title.upper().strip("«»\"'")[:34]
    wrapped = "\n".join(textwrap.wrap(title, width=18)) if len(title) > 18 else title
    return f"«{wrapped}»" if "\n" not in wrapped else f"«{wrapped}»"


async def cover(cfg, repo, text: str, dest: Path, source: Path | None = None) -> MediaResult:
    """16:9 обложка: референс Анжелы + подпись в нижних 20 %, как в dzen/angela.md."""
    if not which("ffmpeg"):
        return MediaResult(hint="в контейнере нет ffmpeg — "
                                "docker compose build пересоберёт образ с ним (см. bot/Dockerfile)")
    src = source or repo.cover_source()
    if not src:
        return MediaResult(hint="не найден референс для обложки: проверьте COVER_SOURCE в bot/.env")
    font = find_font(cfg)
    if not font:
        return MediaResult(hint="не найден шрифт с кириллицей (DejaVu/Liberation/Noto) — "
                                "в образе это пакет fonts-dejavu-core")

    dest.mkdir(parents=True, exist_ok=True)
    out = dest / "cover.jpg"
    cap_file = dest / "caption.txt"
    cap_file.write_text(caption_from(text), encoding="utf-8")

    vf = (
        "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,"
        "drawbox=x=0:y=ih*0.76:w=iw:h=ih*0.24:color=black@0.45:t=fill,"
        f"drawtext=fontfile={font}:textfile={cap_file}:fontcolor=white:"
        "fontsize=54:line_spacing=10:x=48:y=h*0.82"
    )
    code, log = await _run("ffmpeg", "-y", "-i", str(src), "-frames:v", "1",
                           "-vf", vf, "-q:v", "2", str(out))
    if code or not out.exists():
        return MediaResult(hint=f"ffmpeg вернул ошибку: {log[-240:]}")
    return MediaResult([out])


async def slideshow(cfg, images: list[Path], dest: Path, *, audio: Path | None = None,
                    seconds_each: int = 3, vertical: bool = False) -> MediaResult:
    """Тизер из готовых кадров: Ken Burns на 3 сек/кадр, опционально поверх озвучки."""
    if not which("ffmpeg"):
        return MediaResult(hint="нет ffmpeg — ролик не собрать; в Docker-образе он есть (bot/Dockerfile)")
    images = [p for p in images if p.exists()]
    if not images:
        return MediaResult(hint="нет кадров: сначала /иллюстрации или /обложка")
    dest.mkdir(parents=True, exist_ok=True)
    size = "1080:1920" if vertical else "1280:720"
    w, h = size.split(":")
    segs: list[Path] = []
    for i, img in enumerate(images, 1):
        seg = dest / f"seg-{i:02d}.mp4"
        # z=1.0→1.06 даёт лёгкий наезд без дёрганья
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
              f"zoompan=z='min(zoom+0.0015,1.06)':d=25*{seconds_each}:s={w}x{h}:fps=25")
        code, log = await _run("ffmpeg", "-y", "-loop", "1", "-i", str(img),
                               "-t", str(seconds_each), "-vf", vf, "-pix_fmt", "yuv420p",
                               "-c:v", "libx264", "-preset", "veryfast", str(seg))
        if code or not seg.exists():
            return MediaResult(hint=f"сборка кадра {i} не удалась: {log[-240:]}")
        segs.append(seg)

    lst = dest / "list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in segs), encoding="utf-8")
    out = dest / ("teaser-vertical.mp4" if vertical else "teaser.mp4")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if audio and audio.exists():
        cmd += ["-i", str(audio), "-c:a", "aac", "-b:a", "160k", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "copy", str(out)]
    code, log = await _run(*cmd, cwd=dest)
    for seg in segs:
        seg.unlink(missing_ok=True)
    lst.unlink(missing_ok=True)
    if code or not out.exists():
        return MediaResult(hint=f"склейка не удалась: {log[-240:]}")
    return MediaResult([out])


# --- озвучка --------------------------------------------------------------------

VOICES = {
    "f": "ru-RU-SvetlanaNeural",
    "m": "ru-RU-DmitryNeural",
    "tatar-f": "ru-RU-SvetlanaNeural",
}


def voicebox(text: str) -> str:
    """Для ролика озвучиваем только «Текст за кадром» — остальное читать нельзя."""
    m = re.search(r"##\s*Текст за кадром\s*\n(.*?)(?=\n##|\Z)", text, re.S)
    if m:
        lines = [l.strip(" -*\t") for l in m.group(1).splitlines() if l.strip()]
        return " ".join(l for l in lines if l)
    body = re.sub(r"^\s*#.*$", "", text, flags=re.M)
    body = re.sub(r"^\s*\|.*$", "", body, flags=re.M)
    return body.strip()


async def speech(cfg, text: str, dest: Path, rate: str = "+4%") -> MediaResult:
    dest.mkdir(parents=True, exist_ok=True)
    say = voicebox(text) or caption_from(text)
    if not say:
        return MediaResult(hint="нечего озвучивать: в тексте нет блока «Текст за кадром»")
    out = dest / "voice.mp3"

    if cfg.tts_provider in ("edge", ""):
        try:
            import edge_tts  # type: ignore
            await edge_tts.Communicate(say, cfg.tts_voice, rate=rate).save(str(out))
            if out.exists() and out.stat().st_size > 1024:
                return MediaResult([out])
        except ImportError:
            pass
        except Exception as exc:
            return MediaResult(hint=f"edge-tts: {str(exc)[:200]}")

    if which("gtts-cli"):
        code, log = await _run("gtts-cli", "--text", say, "--lang", "ru", "--output",
                              str(out.with_suffix("")))
        if not code and out.exists():
            return MediaResult([out])
        return MediaResult(hint=f"gtts-cli: {log[-200:]}")

    return MediaResult(hint="озвучки нет: pip install edge-tts (нужен выход в internet) "
                            "или пакет gtts в образе")
