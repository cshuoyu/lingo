"""Query monitor geometry on GNOME/Wayland via GTK4."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

_inited = False


def _display() -> Gdk.Display:
    global _inited
    if not _inited:
        Gtk.init()
        _inited = True
    display = Gdk.Display.get_default()
    if display is None:
        raise RuntimeError("No Gdk display available (is $DISPLAY/$WAYLAND_DISPLAY set?)")
    return display


def primary_size() -> tuple[int, int]:
    display = _display()
    monitors = display.get_monitors()
    n = monitors.get_n_items()
    if n == 0:
        raise RuntimeError("No monitors detected")
    monitor = monitors.get_item(0)
    geom = monitor.get_geometry()
    scale = monitor.get_scale_factor() or 1
    return geom.width * scale, geom.height * scale


def all_monitors() -> list[tuple[int, int, int, int]]:
    """Return list of (x, y, width, height) in device pixels for every monitor."""
    display = _display()
    monitors = display.get_monitors()
    out: list[tuple[int, int, int, int]] = []
    for i in range(monitors.get_n_items()):
        m = monitors.get_item(i)
        g = m.get_geometry()
        s = m.get_scale_factor() or 1
        out.append((g.x * s, g.y * s, g.width * s, g.height * s))
    return out
