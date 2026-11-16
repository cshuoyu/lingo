"""Config loading and runtime state for Lingo (multi-collection + random rotation history)."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

APP = "lingo"


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP


def cache_dir() -> Path:
    d = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / APP
    d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULT_TOML = """# Lingo configuration.

[rotation]
active_collection = "default"
interval_minutes = 60

[clock]
enabled = true
side = "left"              # "left" or "right"
time_size = 140
date_size = 88
time_format = "%-I:%M %p"
date_format = "%A, %B %-d"

[compose]
blur = 40

[collections.default]
path = "~/.config/lingo/images"
"""


@dataclass
class Collection:
    name: str
    path: Path


@dataclass
class Config:
    collections: dict[str, Collection]
    active_collection: str = "default"
    interval_minutes: int = 60
    clock_enabled: bool = True
    clock_side: str = "left"
    time_size: int = 140
    date_size: int = 88
    time_format: str = "%-I:%M %p"
    date_format: str = "%A, %B %-d"
    blur: int = 40

    def active(self) -> Collection:
        return self.collections[self.active_collection]

    @classmethod
    def load(cls) -> "Config":
        path = config_dir() / "config.toml"
        if not path.exists():
            default_path = config_dir() / "images"
            return cls(collections={"default": Collection("default", default_path)})

        with path.open("rb") as f:
            data = tomllib.load(f)
        r = data.get("rotation", {})
        c = data.get("clock", {})
        cm = data.get("compose", {})
        coll_data = data.get("collections", {})

        # Back-compat: old schema had [rotation].images_dir
        if not coll_data and "images_dir" in r:
            coll_data = {"default": {"path": r["images_dir"]}}

        collections: dict[str, Collection] = {}
        for name, d in coll_data.items():
            raw = d.get("path", "")
            if not raw:
                continue
            collections[name] = Collection(name=name, path=Path(raw).expanduser())

        if not collections:
            default_path = config_dir() / "images"
            collections = {"default": Collection("default", default_path)}

        active = r.get("active_collection")
        if not active or active not in collections:
            active = next(iter(collections))

        return cls(
            collections=collections,
            active_collection=active,
            interval_minutes=int(r.get("interval_minutes", 60)),
            clock_enabled=bool(c.get("enabled", True)),
            clock_side=str(c.get("side", "left")),
            time_size=int(c.get("time_size", 140)),
            date_size=int(c.get("date_size", 88)),
            time_format=str(c.get("time_format", "%-I:%M %p")),
            date_format=str(c.get("date_format", "%A, %B %-d")),
            blur=int(cm.get("blur", 40)),
        )

    def save(self) -> None:
        sections: list[tuple[str, dict]] = [
            ("rotation", {
                "active_collection": self.active_collection,
                "interval_minutes": self.interval_minutes,
            }),
            ("clock", {
                "enabled": self.clock_enabled,
                "side": self.clock_side,
                "time_size": self.time_size,
                "date_size": self.date_size,
                "time_format": self.time_format,
                "date_format": self.date_format,
            }),
            ("compose", {
                "blur": self.blur,
            }),
        ]
        for name, coll in self.collections.items():
            sections.append((f"collections.{name}", {
                "path": _contract_home(coll.path),
            }))
        body = "# Lingo configuration.\n\n" + _dump_toml(sections)
        (config_dir() / "config.toml").write_text(body)


def _contract_home(p: Path) -> str:
    s = str(p)
    home = str(Path.home())
    if s == home:
        return "~"
    if s.startswith(home + "/"):
        return "~" + s[len(home):]
    return s


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    raise TypeError(f"Cannot serialize {type(v).__name__}")


def _dump_toml(sections: list[tuple[str, dict]]) -> str:
    lines: list[str] = []
    for name, values in sections:
        lines.append(f"[{name}]")
        for k, v in values.items():
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


@dataclass
class State:
    last_rotation: str = ""
    slot: str = "a"
    recent: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "State":
        p = cache_dir() / "state.json"
        if not p.exists():
            return cls()
        try:
            d = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return cls()
        return cls(
            last_rotation=str(d.get("last_rotation", "")),
            slot=str(d.get("slot", "a")),
            recent={str(k): [str(x) for x in v] for k, v in d.get("recent", {}).items()},
        )

    def save(self) -> None:
        (cache_dir() / "state.json").write_text(json.dumps({
            "last_rotation": self.last_rotation,
            "slot": self.slot,
            "recent": self.recent,
        }, indent=2))

    def push_recent(self, collection: str, filename: str, cap: int = 20) -> None:
        lst = self.recent.setdefault(collection, [])
        if filename in lst:
            lst.remove(filename)
        lst.insert(0, filename)
        del lst[cap:]

    def current_for(self, collection: str) -> str | None:
        lst = self.recent.get(collection, [])
        return lst[0] if lst else None
