"""Lingo CLI.

Subcommands:
  tick        - re-render current wallpaper; rotate if interval elapsed (used by timer)
  next        - pick a new random image from the active collection
  prev        - go back to the previously shown image in the active collection
  apply       - apply an arbitrary image file (outside any collection)
  render      - compose a wallpaper and save to a file (preview / debug)
  status      - print current config + state + selected image
  collections - list collections
  switch      - switch the active collection
  new         - create a new collection folder
  gui         - launch the GTK4 settings/browser window
  restart     - reload + restart the systemd user timer (triggers one tick)
  install     - set up ~/.config/lingo/, seed images from Variety, install systemd units
"""

from __future__ import annotations

import argparse
import datetime as dt
import locale
import os
import shutil
import subprocess
import sys
from pathlib import Path

from compositor import compose
from config import Collection, Config, DEFAULT_TOML, State, config_dir
from rotator import list_images, pick_random, scheduled_rotation_due
from screen import primary_size
from wallpaper import clock_from_cfg, compose_and_apply

try:
    locale.setlocale(locale.LC_TIME, "en_US.UTF-8")
except locale.Error:
    pass


PROJECT_DIR = Path(__file__).resolve().parent
VARIETY_FAVORITES = Path.home() / ".config/variety/Favorites"
LOCAL_BIN = Path.home() / ".local/bin"
SYSTEMD_USER_DIR = Path.home() / ".config/systemd/user"
UNIT_NAME = "lingo"


# ---------- subcommands ----------

def cmd_tick(args: argparse.Namespace) -> None:
    cfg = Config.load()
    state = State.load()
    coll = cfg.active()
    images = list_images(coll.path)
    if not images:
        return
    recent = state.recent.get(coll.name, [])
    startup = getattr(args, "startup", False)
    due = (cfg.update_on_start if startup else scheduled_rotation_due(cfg, state.last_rotation))
    if due:
        pick = pick_random(images, recent)
        if pick is None:
            return
        state.push_recent(coll.name, pick.name)
        state.last_rotation = dt.datetime.now().isoformat(timespec="seconds")
    else:
        if not recent or not cfg.clock_enabled:
            return
        current_name = recent[0]
        matches = [p for p in images if p.name == current_name]
        pick = matches[0] if matches else pick_random(images, recent)
        if pick is None:
            return
    compose_and_apply(cfg, state, pick)
    state.save()


def cmd_next(_: argparse.Namespace) -> None:
    cfg = Config.load()
    state = State.load()
    coll = cfg.active()
    images = list_images(coll.path)
    if not images:
        sys.exit(f"No images in {coll.path}")
    recent = state.recent.get(coll.name, [])
    pick = pick_random(images, recent)
    state.push_recent(coll.name, pick.name)
    state.last_rotation = dt.datetime.now().isoformat(timespec="seconds")
    compose_and_apply(cfg, state, pick)
    state.save()
    print(f"→ [{coll.name}] {pick.name}")


def cmd_prev(_: argparse.Namespace) -> None:
    cfg = Config.load()
    state = State.load()
    coll = cfg.active()
    images = list_images(coll.path)
    if not images:
        sys.exit(f"No images in {coll.path}")
    recent = state.recent.get(coll.name, [])
    if len(recent) < 2:
        sys.exit("No previous image in history.")
    # Drop current, promote previous to front
    current = recent.pop(0)
    prev_name = recent[0]
    matches = [p for p in images if p.name == prev_name]
    if not matches:
        # Previous file disappeared — just pick random, restore history
        recent.insert(0, current)
        pick = pick_random(images, recent)
        state.push_recent(coll.name, pick.name)
    else:
        pick = matches[0]
    state.last_rotation = dt.datetime.now().isoformat(timespec="seconds")
    compose_and_apply(cfg, state, pick)
    state.save()
    print(f"← [{coll.name}] {pick.name}")


def cmd_apply(args: argparse.Namespace) -> None:
    cfg = Config.load()
    state = State.load()
    compose_and_apply(cfg, state, args.image)
    state.save()
    print(f"applied {args.image.name}")


def cmd_render(args: argparse.Namespace) -> None:
    cfg = Config.load()
    w, h = (
        tuple(int(x) for x in args.size.lower().split("x"))
        if args.size
        else primary_size()
    )
    clock = clock_from_cfg(cfg) if not args.no_clock else None
    img = compose(args.image, (w, h), clock=clock, blur_radius=cfg.blur, fill_style=cfg.fill_style)
    img.save(args.output)
    print(f"wrote {args.output} ({w}x{h})")


def cmd_status(_: argparse.Namespace) -> None:
    cfg = Config.load()
    state = State.load()
    coll = cfg.active()
    images = list_images(coll.path)
    recent = state.recent.get(coll.name, [])
    current = recent[0] if recent else None
    print(f"config dir        : {config_dir()}")
    print(f"active collection : {coll.name} ({coll.path})")
    print(f"image count       : {len(images)}")
    print(f"interval (min)    : {cfg.interval_minutes}")
    print(f"clock             : {'on' if cfg.clock_enabled else 'off'} ({cfg.clock_side})")
    print(f"last rotation     : {state.last_rotation or '—'}")
    print(f"current image     : {current or '(none)'}")
    print(f"collections       : {', '.join(cfg.collections)}")


def cmd_collections(_: argparse.Namespace) -> None:
    cfg = Config.load()
    for name, coll in cfg.collections.items():
        marker = "*" if name == cfg.active_collection else " "
        count = len(list_images(coll.path))
        print(f"{marker} {name:<20} {count:>4} images   {coll.path}")


def cmd_switch(args: argparse.Namespace) -> None:
    cfg = Config.load()
    if args.name not in cfg.collections:
        sys.exit(f"Unknown collection: {args.name}. Known: {', '.join(cfg.collections)}")
    cfg.active_collection = args.name
    cfg.save()
    print(f"active collection → {args.name}")
    # Immediately rotate to show something from the new collection
    state = State.load()
    images = list_images(cfg.collections[args.name].path)
    if not images:
        print(f"(collection is empty: {cfg.collections[args.name].path})")
        return
    recent = state.recent.get(args.name, [])
    pick = pick_random(images, recent)
    state.push_recent(args.name, pick.name)
    state.last_rotation = dt.datetime.now().isoformat(timespec="seconds")
    compose_and_apply(cfg, state, pick)
    state.save()
    print(f"→ {pick.name}")


def cmd_new(args: argparse.Namespace) -> None:
    cfg = Config.load()
    if args.name in cfg.collections:
        sys.exit(f"Collection already exists: {args.name}")
    path = Path(args.path).expanduser() if args.path else (config_dir() / args.name)
    path.mkdir(parents=True, exist_ok=True)
    cfg.collections[args.name] = Collection(name=args.name, path=path)
    cfg.save()
    print(f"created collection {args.name} → {path}")


def cmd_gui(_: argparse.Namespace) -> None:
    import gui
    gui.run()


def cmd_restart(_: argparse.Namespace) -> None:
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "restart", f"{UNIT_NAME}.timer"], check=True)
    subprocess.run(["systemctl", "--user", "start", f"{UNIT_NAME}.service"], check=True)
    print(f"restarted {UNIT_NAME}.timer and triggered one tick")


# ---------- install ----------

LINGO_SCRIPT = """#!/bin/sh
exec {python} {project}/main.py "$@"
"""


def _copy_variety_favorites(dst: Path) -> int:
    if not VARIETY_FAVORITES.exists():
        return 0
    count = 0
    for src in VARIETY_FAVORITES.iterdir():
        if not src.is_file():
            continue
        target = dst / src.name
        if target.exists():
            continue
        shutil.copy2(src, target)
        count += 1
    return count


def cmd_install(args: argparse.Namespace) -> None:
    python = sys.executable

    # 1. config dir + config.toml (write default only if missing)
    config_dir().mkdir(parents=True, exist_ok=True)
    toml_path = config_dir() / "config.toml"
    if not toml_path.exists():
        toml_path.write_text(DEFAULT_TOML)
        print(f"wrote {toml_path}")
    else:
        print(f"kept  {toml_path}")

    # 2. load config (triggers old-schema back-compat) and re-save in new schema
    cfg = Config.load()
    cfg.save()
    print(f"normalized {toml_path}")

    # 3. images dir + seed from Variety favorites (into default collection)
    for coll in cfg.collections.values():
        coll.path.mkdir(parents=True, exist_ok=True)
    default = cfg.collections.get("default")
    if default is not None:
        n = _copy_variety_favorites(default.path)
        print(f"images: {default.path} ({n} copied from Variety Favorites)")

    # 4. lingo shim in ~/.local/bin
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    shim = LOCAL_BIN / "lingo"
    shim.write_text(LINGO_SCRIPT.format(python=python, project=PROJECT_DIR))
    shim.chmod(0o755)
    print(f"wrote {shim}")

    # Install the same schedule managed by the Settings page.
    from scheduler import sync_schedule
    cfg.autostart = not args.no_enable
    cfg.save()
    sync_schedule(cfg, start_current=not args.no_enable)
    print("installed wallpaper schedule")

    # 7. warnings
    variety_autostart = Path.home() / ".config/autostart/variety.desktop"
    if variety_autostart.exists():
        print(
            "\n⚠  Variety autostart still present at:\n"
            f"   {variety_autostart}\n"
            "   If Variety is running it will override this app's wallpaper.\n"
            "   Run  `variety --quit`  now, and to keep it off at login run:\n"
            f"   rm '{variety_autostart}'"
        )
    if str(LOCAL_BIN) not in os.environ.get("PATH", "").split(":"):
        print(f"\nℹ  Add {LOCAL_BIN} to PATH to use the `lingo` shortcut.")


# ---------- argparse ----------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="lingo", description="Lingo")
    sub = p.add_subparsers(dest="cmd", required=True)

    tick = sub.add_parser("tick", help="Re-render clock and rotate according to schedule")
    tick.add_argument("--startup", action="store_true", help="Apply login update preference")
    tick.set_defaults(func=cmd_tick)
    sub.add_parser("next", help="Random next image from active collection").set_defaults(
        func=cmd_next
    )
    sub.add_parser("prev", help="Go back to previous image").set_defaults(func=cmd_prev)
    sub.add_parser("status", help="Print current config + state").set_defaults(func=cmd_status)
    sub.add_parser("collections", help="List collections").set_defaults(func=cmd_collections)
    sub.add_parser("gui", help="Open the GTK4 settings/browser window").set_defaults(func=cmd_gui)
    sub.add_parser("restart", help="Reload + restart the systemd timer").set_defaults(
        func=cmd_restart
    )

    s = sub.add_parser("switch", help="Switch active collection")
    s.add_argument("name")
    s.set_defaults(func=cmd_switch)

    n = sub.add_parser("new", help="Create a new collection")
    n.add_argument("name")
    n.add_argument("--path", help="Folder for the new collection (default: ~/.config/lingo/<name>)")
    n.set_defaults(func=cmd_new)

    a = sub.add_parser("apply", help="Apply an arbitrary image as wallpaper")
    a.add_argument("image", type=Path)
    a.set_defaults(func=cmd_apply)

    r = sub.add_parser("render", help="Compose and write PNG to file (preview)")
    r.add_argument("image", type=Path)
    r.add_argument("-o", "--output", type=Path, default=Path("out.png"))
    r.add_argument("--size", help="Override screen size, e.g. 2560x1440")
    r.add_argument("--no-clock", action="store_true")
    r.set_defaults(func=cmd_render)

    i = sub.add_parser(
        "install",
        help="Set up ~/.config/lingo, copy Variety favorites, install systemd units",
    )
    i.add_argument("--no-enable", action="store_true", help="Write units but don't enable/start")
    i.set_defaults(func=cmd_install)

    return p.parse_args()


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
