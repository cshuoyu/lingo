"""Image pool enumeration, rotation-due check, and random picking with recent history."""

from __future__ import annotations

import datetime as dt
import random
from pathlib import Path

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def list_images(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in EXTS)


def rotation_due(last_iso: str, interval_minutes: int, now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now()
    if not last_iso:
        return True
    try:
        last = dt.datetime.fromisoformat(last_iso)
    except ValueError:
        return True
    return (now - last).total_seconds() >= interval_minutes * 60


def pick_random(images: list[Path], recent: list[str], avoid: int = 5) -> Path | None:
    if not images:
        return None
    exclude = set(recent[:avoid])
    pool = [p for p in images if p.name not in exclude]
    if not pool:
        pool = images
    return random.choice(pool)
