#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Установщик COOKRATE Bot.

Один файл вместо скриптов под Windows и Linux: он же проверяет Python, он же ставит
зависимости, он же создаёт bot/.env и просит токен, он же прогоняет самопроверку.

    python bot/install.py              # полная установка (Windows, macOS, Linux)
    python bot/install.py --check      # ничего не ставить: только проверить сборку
    python bot/install.py --token 123:ABC --admin 123456789 --no-prompt
    python bot/install.py --docker     # подсказать команды для Docker и выйти

После установки бот запускается командой, которую установщик напечатает в конце.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # <repo>/bot
REPO = HERE.parent
VENV = REPO / ".venv"
ENV_FILE = HERE / ".env"
ENV_EXAMPLE = HERE / ".env.example"
MIN_PY = (3, 10)

OK, FAIL, ARROW = "  ✔", "  ✗", "  →"

# построчная буферизация: иначе при `python bot/install.py | tee log` выводы дочерних
# команды обгоняют наши print'ы и порядок строк съезжает
try:
    sys.stdout.reconfigure(line_buffering=True)   # type: ignore[union-attr]
except Exception:
    pass


def say(mark: str, text: str) -> None:
    print(f"{mark} {text}")


def run(cmd: list[str], **kw) -> int:
    """Прогон команды с наследованием вывода; возвращает код возврата."""
    print(f"{ARROW} $ {' '.join(str(c) for c in cmd)}")
    return subprocess.call([str(c) for c in cmd], cwd=str(REPO), **kw)


def py_bin(venv: Path) -> Path:
    return (venv / "Scripts" / "python.exe") if os.name == "nt" else (venv / "bin" / "python")


def check_python() -> tuple[bool, str]:
    v = sys.version_info
    if (v.major, v.minor) < MIN_PY:
        return False, f"Python {v.major}.{v.minor} — нужно {MIN_PY[0]}.{MIN_PY[1]} или новее"
    return True, f"Python {v.major}.{v.minor}.{v.micro}"


def check_repo() -> tuple[bool, str]:
    need = [REPO / "dzen" / "tools" / "cookrate.py", REPO / "dzen" / "channel.md",
            REPO / "dzen" / "angela.md", HERE / "__main__.py"]
    missing = [str(p.relative_to(REPO)) for p in need if not p.exists()]
    if missing:
        return False, "нет файлов: " + ", ".join(missing)
    return True, f"репозиторий: {REPO}"


def check_ffmpeg() -> tuple[bool, str]:
    if shutil.which("ffmpeg"):
        return True, "ffmpeg найден — обложки и тизеры будут работать"
    hint = ("apt install ffmpeg fonts-dejavu-core (Linux) · brew install ffmpeg (macOS) · "
            "winget install Gyan.FFmpeg (Windows) · либо Docker, где он уже есть")
    return False, "ffmpeg не найден — бот заработает, но без обложек/тизеров. " + hint


def venv_python() -> Path | None:
    p = py_bin(VENV)
    return p if p.exists() else None


def make_venv() -> bool:
    if venv_python():
        say(OK, f"venv уже есть: {VENV}")
        return True
    say(ARROW, f"создаю виртуальное окружение в {VENV}")
    if run([sys.executable, "-m", "venv", VENV]) != 0:
        say(FAIL, "venv не создался — на Linux часто помогает: sudo apt install python3-venv")
        return False
    return True


def install_deps(python: Path) -> bool:
    req = HERE / "requirements.txt"
    if run([python, "-m", "pip", "install", "--disable-pip-version-check", "-q",
            "--upgrade", "pip"]) != 0:
        return False
    if run([python, "-m", "pip", "install", "--disable-pip-version-check", "-q",
            "-r", str(req)]) != 0:
        say(FAIL, "не удалось поставить зависимости. Проверьте интернет и прокси.")
        return False
    say(OK, "зависимости поставлены (aiogram, aiohttp, edge-tts)")
    return True


def read_env_keys(path: Path) -> dict[str, str]:
    out = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def write_env_token(token: str, admin: str) -> None:
    """Создаёт .env из примера и вписывает токен/admin id, не трогая остальные строки."""
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines() if ENV_EXAMPLE.exists() else []
    wanted = {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_ADMIN_ID": admin}
    done = set()
    out = []
    for line in lines:
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m and m.group(1) in wanted:
            out.append(f"{m.group(1)}={wanted[m.group(1)]}")
            done.add(m.group(1))
        else:
            out.append(line)
    for k, v in wanted.items():
        if k not in done and v:
            out.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass


def setup_env(args) -> bool:
    have = read_env_token(ENV_FILE)
    if have and not args.force_env:
        say(OK, f"bot/.env уже есть, токен задан — не трогаю (--force-env перезаписать)")
        return True
    token = args.token or ""
    admin = args.admin or ""
    if not token and not args.no_prompt and sys.stdin.isatty():
        print("\nТокен выдаёт @BotFather: /newbot → имя → скопировать строку 123456:ABC-DEF…")
        token = input("  TELEGRAM_BOT_TOKEN (Enter — пропустить): ").strip()
        admin = input("  TELEGRAM_ADMIN_ID (Enter — пропустить): ").strip()
    if not token:
        say(FAIL, "токена нет. Пропишите его в bot/.env вручную и перезапустите установщик.")
        return False
    write_env_token(token, admin)
    say(OK, f"записал bot/.env (токен задан, права 600; в git он не попадёт)")
    return True


def read_env_token(path: Path) -> str:
    return read_env_keys(path).get("TELEGRAM_BOT_TOKEN", "")


def selftest(python: Path) -> bool:
    print()
    env = dict(os.environ, COOKRATE_REPO=str(REPO))
    return run([python, "-m", "bot", "--selftest"], env=env) == 0


def finish(python: Path | None) -> None:
    act = (r".venv\Scripts\activate" if os.name == "nt" else "source .venv/bin/activate")
    exe = python or sys.executable
    print("\nГотово. Запускать бота так:\n")
    print(f"  cd {REPO}")
    print(f"  {exe} -m bot")
    print("\nили в постоянном режиме (остаётся работать после закрытия терминала):")
    if os.name == "nt":
        print(r"  powershell -WindowStyle Hidden -Command """ + str(exe) + " -m bot""")
    else:
        print(f"  nohup {exe} -m bot > bot.log 2>&1 &      # стоп:  pkill -f 'python -m bot'")
    print("\nОстановить: Ctrl+C. Логи — в консоли, ошибки Telegram — там же.")


def main() -> int:
    p = argparse.ArgumentParser(description="установка COOKRATE Bot")
    p.add_argument("--token", default="", help="токен из @BotFather (чтобы не спрашивать)")
    p.add_argument("--admin", default="", help="ваш числовой chat id")
    p.add_argument("--check", action="store_true", help="только проверить, ничего не ставить")
    p.add_argument("--no-venv", action="store_true", help="ставить в текущий интерпретатор")
    p.add_argument("--no-prompt", action="store_true", help="не задавать вопросов (для CI)")
    p.add_argument("--force-env", action="store_true", help="перезаписать bot/.env")
    p.add_argument("--docker", action="store_true", help="показать команды Docker и выйти")
    args = p.parse_args()

    print("COOKRATE Bot — установка\n" + "─" * 46)
    for fn in (check_python, check_repo, check_ffmpeg):
        good, msg = fn()
        say(OK if good else FAIL, msg)
        if fn is not check_ffmpeg and not good:
            print("\nДальше нельзя: исправьте отмеченное и повторите.")
            return 1

    if args.docker:
        print(f"\nDocker-путь (ffmpeg и шрифт уже в образе):\n"
              f"  cp bot/.env.example bot/.env    # вписать TELEGRAM_BOT_TOKEN и TELEGRAM_ADMIN_ID\n"
              f"  docker compose -f bot/docker-compose.yml up -d --build\n"
              f"  docker compose -f bot/docker-compose.yml logs -f")
        return 0

    if args.check:
        python = venv_python() or Path(sys.executable)
        return 0 if selftest(python) else 1

    if args.no_venv:
        python = Path(sys.executable)
        if not install_deps(python):
            return 1
    else:
        if not make_venv():
            return 1
        python = venv_python()
        if not python or not install_deps(python):
            return 1

    if not setup_env(args):
        print("\nМожно установить без токена, а потом дописать его в bot/.env.")
        finish(python if not args.no_venv else None)
        return 0

    ok = selftest(python)
    finish(python if not args.no_venv else None)
    if not ok:
        print("\n⚠️  самотест не прошёл — смотрите вывод выше, обычно это путь к репозиторию")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
