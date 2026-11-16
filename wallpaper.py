"""Apply a composed image as the GNOME desktop wallpaper via Gio.Settings (batched)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

from compositor import ClockStyle, compose
from config import Config, State, cache_dir
from screen import primary_size

_BG_SCHEMA = "org.gnome.desktop.background"


def slot_path(slot: str) -> Path:
    return cache_dir() / f"current_{slot}.png"


def flip_slot(current: str) -> str:
    return "b" if current == "a" else "a"


def apply_file(path: Path) -> None:
    """Set wallpaper URIs atomically so GNOME sees one change, not three."""
    uri = path.resolve().as_uri()
    settings = Gio.Settings.new(_BG_SCHEMA)
    settings.delay()
    if settings.get_string("picture-uri") != uri:
        settings.set_string("picture-uri", uri)
    if settings.get_string("picture-uri-dark") != uri:
        settings.set_string("picture-uri-dark", uri)
    if settings.get_string("picture-options") != "zoom":
        settings.set_string("picture-options", "zoom")
    settings.apply()
    Gio.Settings.sync()


def clock_from_cfg(cfg: Config) -> ClockStyle | None:
    if not cfg.clock_enabled:
        return None
    now = dt.datetime.now()
    return ClockStyle(
        lines=[now.strftime(cfg.time_format), now.strftime(cfg.date_format)],
        font_sizes=[cfg.time_size, cfg.date_size],
        side=cfg.clock_side,
    )


def compose_and_apply(cfg: Config, state: State, image_path: Path) -> Path:
    w, h = primary_size()
    img = compose(image_path, (w, h), clock=clock_from_cfg(cfg), blur_radius=cfg.blur, fill_style=cfg.fill_style)
    state.slot = flip_slot(state.slot)
    out = slot_path(state.slot)
    tmp = out.with_suffix(out.suffix + ".part")
    img.save(tmp, format="PNG")
    tmp.replace(out)
    apply_file(out)
    return out
