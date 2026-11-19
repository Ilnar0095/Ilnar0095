"""Работа с репозиторием канала: нумерация, слаг, сохранение, линт, план.

Единственный источник правил качества — dzen/tools/cookrate.py. Бот его импортирует,
а не переписывает: поменяли чек-лист в репо — поменялись проверки в Telegram.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import re
import sys
from dataclasses import dataclass

PUBLISHED = "published"


@dataclass
class LintResult:
    path: str
    errors: tuple[str, ...]
    warns: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def report(self) -> str:
        lines = [f"📄 {self.path}"]
        lines += [f"❌ {e}" for e in self.errors]
        lines += [f"⚠️ {w}" for w in self.warns]
        if self.ok and not self.warns:
            lines.append("✅ чисто: можно копировать в Дзен")
        return "\n".join(lines)


def cookrate_module(repo: pathlib.Path):
    """Грузит dzen/tools/cookrate.py по пути, не полагаясь на PYTHONPATH."""
    tools = repo / "dzen" / "tools"
    target = tools / "cookrate.py"
    if not target.exists():
        for guess in (pathlib.Path.cwd() / "dzen/tools", pathlib.Path("/app/repo/dzen/tools")):
            if (guess / "cookrate.py").exists():
                target = guess / "cookrate.py"
                break
    if not target.exists():
        raise FileNotFoundError(f"не найден {tools / 'cookrate.py'} — проверьте COOKRATE_REPO")
    name = "cookrate_repo"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, target)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# --- слаг и номер ---------------------------------------------------------------

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}


def slugify(text: str, maxlen: int = 34) -> str:
    out = []
    for ch in text.lower():
        if ch in TRANSLIT:
            out.append(TRANSLIT[ch])
        elif ch.isascii() and (ch.isalnum() or ch in "- "):
            out.append("-" if ch == " " else ch)
        else:
            out.append("-")
    slug = re.sub(r"-+", "-", "".join(out)).strip("-")
    words, total = [], 0
    for w in slug.split("-"):
        if total + len(w) + 1 > maxlen:
            break
        words.append(w)
        total += len(w) + 1
    return "-".join(words) or "publication"


def parse_frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "-")):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"')
    return fm


class Repo:
    def __init__(self, cfg):
        self.cfg = cfg
        self.root: pathlib.Path = cfg.repo
        self.dzen = self.root / "dzen"
        self.next_dir = self.dzen / "next"
        self.work = cfg.workdir
        self.work.mkdir(parents=True, exist_ok=True)
        try:
            self._ck = cookrate_module(self.root)
        except FileNotFoundError:
            self._ck = None

    # --- нумерация --------------------------------------------------------------

    def _all_publications(self) -> list[pathlib.Path]:
        files: list[pathlib.Path] = []
        for folder in ("published", "next"):
            d = self.dzen / folder
            if d.exists():
                files += sorted(d.glob("*.md"))
        return files

    def next_number(self) -> str:
        nums = []
        for f in self._all_publications():
            m = re.match(r"(\d+)", f.stem)
            if m:
                nums.append(int(m.group(1)))
        return str(max(nums) + 1 if nums else 1).zfill(3)

    def used_slugs(self) -> set[str]:
        return {f.stem.split("-", 1)[-1] for f in self._all_publications() if "-" in f.stem}

    def free_path(self, number: str, slug: str) -> pathlib.Path:
        slug = re.sub(r"[^a-z0-9-]", "", slug) or "publication"
        candidate = self.next_dir / f"{number}-{slug}.md"
        n = 2
        while candidate.exists():
            candidate = self.next_dir / f"{number}-{slug}-{n}.md"
            n += 1
        return candidate

    # --- сохранение --------------------------------------------------------------

    def save_draft(self, text: str, *, kind: str, topic: str, number: str | None = None,
                   date: str | None = None) -> pathlib.Path:
        number = number or self.next_number()
        fm = parse_frontmatter(text)
        slug = slugify(fm.get("slug") or topic)
        path = self.free_path(number, slug)
        if not text.lstrip().startswith("---"):
            text = self.wrap_frontmatter(text, number=number, kind=kind, topic=topic,
                                         date=date or dt.date.today().isoformat())
        self.next_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def wrap_frontmatter(self, text: str, *, number: str, kind: str, topic: str, date: str) -> str:
        rubric = {"article": "🔪 Неожиданное сочетание",
                  "post": "💸 Необычно, но дёшево",
                  "video": "✨ На эффект"}.get(kind, "✨ На эффект")
        fm = "\n".join([
            "---",
            f"number: {number}",
            f"type: {kind if kind != 'video' else 'video-script'}",
            f'rubric: "{rubric}"',
            f"date: {date}",
            "status: draft",
            f"topic: \"{topic}\"",
            "---",
            "",
        ])
        return fm + text

    # --- линт -------------------------------------------------------------------

    def lint(self, path: pathlib.Path):
        if self._ck is None:
            return None
        rep = self._ck.check_file(path, self.root)
        if rep is None:
            return LintResult(str(path.relative_to(self.root)), (), ("файл без YAML `number:` — линтер пропускает",))
        return LintResult(str(path.relative_to(self.root)), tuple(rep.errors), tuple(rep.warns))

    def lint_text(self, text: str) -> LintResult | None:
        """Линт без записи в репозиторий: пишем во временный файл."""
        tmp = self.work / f"lint-{dt.datetime.now():%H%M%S%f}.md"
        tmp.write_text(text, encoding="utf-8")
        try:
            if self._ck is None:
                return None
            rep = self._ck.check_file(tmp, self.work)
            if rep is None:
                return LintResult("черновик", (), ("нет YAML-шапки — линтер пропускает",))
            return LintResult("черновик", tuple(rep.errors), tuple(rep.warns))
        finally:
            tmp.unlink(missing_ok=True)

    # --- план -------------------------------------------------------------------

    def plan(self, week: int | None = None) -> str:
        plan_file = self.dzen / "content-plan.md"
        if not plan_file.exists():
            return "контент-план не найден: dzen/content-plan.md"
        cur, rows = "", []
        for line in plan_file.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^##+\s*(Неделя\s*\d+[^\n]*)", line)
            if m:
                cur = m.group(1).strip()
                continue
            if not line.strip().startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 3 or cells[0] in ("Дата", "") or set(cells[0]) <= set("-: "):
                continue
            rows.append((cur, cells))
        out = []
        for section, cells in rows:
            m = re.search(r"Неделя\s*(\d+)", section)
            if week and (not m or int(m.group(1)) != week):
                continue
            date, rubric, topic = cells[0], cells[1], cells[2]
            out.append(f"{date} {rubric} — {topic}")
        return "\n".join(out) or "для такой недели слотов нет"

    # --- утилиты для текстов ------------------------------------------------------

    def channel_passport(self, limit: int = 6000) -> str:
        f = self.dzen / "channel.md"
        if not f.exists():
            return ""
        text = re.sub(r"^---.*?---\s*", "", f.read_text(encoding="utf-8"), flags=re.S)
        return text[:limit]

    def angela_prompt(self) -> str:
        """Достаёт из dzen/angela.md цитату-шаблон промпта — единый источник стиля."""
        f = self.dzen / "angela.md"
        if not f.exists():
            return ""
        block = re.search(r"Как генерировать следующие кадры.*?(?=\n##|\Z)",
                          f.read_text(encoding="utf-8"), re.S)
        if not block:
            return ""
        quotes = [re.sub(r"^>\s?", "", l).strip() for l in block.group(0).splitlines()
                  if l.startswith(">")]
        return " ".join(q for q in quotes if q)

    def cover_source(self) -> pathlib.Path | None:
        p = self.root / self.cfg.cover_source
        return p if p.exists() else None

    def assets(self) -> list[pathlib.Path]:
        d = self.dzen / "assets"
        return sorted(d.glob("*.[jp][pn]g")) if d.exists() else []
