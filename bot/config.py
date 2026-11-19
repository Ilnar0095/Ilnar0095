"""Конфигурация бота: окружение → один читаемый объект.

Ключей python-dotenv не просим: свой парсер .env на 15 строк, чтобы `pip install`
сводился к aiogram + aiohttp + edge-tts.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: Path) -> None:
    """Загружает bot/.env в os.environ (не перетирая то, что уже задано)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


@dataclass
class Config:
    # доступ
    token: str = ""
    admin_id: int = 0
    allowed_chats: tuple[int, ...] = ()

    # репозиторий
    repo: Path = field(default_factory=lambda: Path("/app/repo"))

    # тексты
    llm_format: str = "none"          # openai | anthropic | none
    llm_key: str = ""
    llm_base: str = ""
    llm_model: str = ""
    llm_temperature: float = 0.7
    llm_max_tokens: int = 3000

    # картинки
    image_provider: str = "none"       # none | openai | replicate
    image_model: str = ""
    image_size: str = "1536x1024"
    replicate_token: str = ""

    # видео
    video_provider: str = "none"       # none | replicate
    video_model: str = ""
    video_seconds: int = 4

    # озвучка
    tts_provider: str = "edge"         # edge | gtts | none
    tts_voice: str = "ru-RU-SvetlanaNeural"

    # обложки без генерации
    cover_source: str = "dzen/assets/angela-01-kurica-s-apelsinom.png"
    cover_font: str = ""

    # поведение
    autosave: bool = True              # сохранять черновики в dzen/next/
    workdir: Path = field(default_factory=Path)   # временная папка для медиа

    @classmethod
    def from_env(cls) -> "Config":
        here = Path(__file__).resolve().parent
        load_dotenv(here / ".env")
        load_dotenv(here.parent / ".env")

        repo = Path(_env("COOKRATE_REPO") or here.parent)
        if not (repo / "dzen").exists():
            # докер: репозиторий может лежать в /app/repo
            for guess in (Path("/app/repo"), here.parent.parent):
                if (guess / "dzen").exists():
                    repo = guess
                    break

        chats = tuple(int(x) for x in _env("TELEGRAM_ALLOWED_CHATS").split(",") if x.strip().isdigit())
        return cls(
            token=_env("TELEGRAM_BOT_TOKEN"),
            admin_id=int(_env("TELEGRAM_ADMIN_ID") or 0),
            allowed_chats=chats,
            repo=repo,
            llm_format=_env("LLM_FORMAT", "none").lower(),
            llm_key=_env("LLM_API_KEY"),
            llm_base=_env("LLM_BASE_URL", "https://api.openai.com/v1"),
            llm_model=_env("LLM_MODEL"),
            llm_temperature=float(_env("LLM_TEMPERATURE") or 0.7),
            llm_max_tokens=int(_env("LLM_MAX_TOKENS") or 3000),
            image_provider=_env("IMAGE_PROVIDER", "none").lower(),
            image_model=_env("IMAGE_MODEL"),
            image_size=_env("IMAGE_SIZE", "1536x1024"),
            replicate_token=_env("REPLICATE_API_TOKEN"),
            video_provider=_env("VIDEO_PROVIDER", "none").lower(),
            video_model=_env("VIDEO_MODEL"),
            video_seconds=int(_env("VIDEO_SECONDS") or 4),
            tts_provider=_env("TTS_PROVIDER", "edge").lower(),
            tts_voice=_env("TTS_VOICE", "ru-RU-SvetlanaNeural"),
            cover_source=_env("COVER_SOURCE", "dzen/assets/angela-01-kurica-s-apelsinom.png"),
            cover_font=_env("COVER_FONT"),
            autosave=_env("COOKRATE_AUTOSAVE", "1") not in ("0", "false", "no"),
            workdir=Path(_env("COOKRATE_WORKDIR") or (here / ".tmp")),
        )

    # --- возможности, от которых зависит UI ------------------------------------

    @property
    def can_write(self) -> bool:
        return bool(self.llm_key) and self.llm_format in ("openai", "anthropic")

    @property
    def can_draw(self) -> bool:
        if self.image_provider == "openai":
            return bool(self.llm_key)
        if self.image_provider == "replicate":
            return bool(self.replicate_token) and bool(self.image_model)
        return False

    @property
    def can_video(self) -> bool:
        return self.video_provider == "replicate" and bool(self.replicate_token) and bool(self.video_model)

    @property
    def tts_ready(self) -> bool:
        if self.tts_provider == "none":
            return False
        import importlib.util, shutil
        if self.tts_provider == "edge" and importlib.util.find_spec("edge_tts"):
            return True
        return shutil.which("gtts-cli") is not None

    @property
    def has_ffmpeg(self) -> bool:
        import shutil
        return shutil.which("ffmpeg") is not None

    def allowed(self, chat_id: int | None) -> bool:
        chats = set(self.allowed_chats) | ({self.admin_id} if self.admin_id else set())
        return not chats or (chat_id in chats)

    def status(self) -> dict[str, bool]:
        return {
            "текст через LLM": self.can_write,
            "картинки через ИИ": self.can_draw,
            "видео через ИИ": self.can_video,
            "обложки/тизеры (ffmpeg)": self.has_ffmpeg,
            "озвучка": self.tts_ready,
        }
