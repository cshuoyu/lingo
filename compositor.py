"""Compose a wallpaper: blurred cover-fill background + contained source + optional clock overlay."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


SERIF_FALLBACKS = (
    "/usr/share/fonts/lm/lmroman10-regular.otf",
    "/usr/share/fonts/liberation-serif-fonts/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/dejavu-serif-fonts/DejaVuSerif.ttf",
    "/usr/share/fonts/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/google-noto-vf/NotoSerif[wght].ttf",
)


@dataclass
class ClockStyle:
    lines: list[str]
    font_sizes: list[int]
    font_path: str | None = None
    line_spacing: int = 16
    color: tuple[int, int, int, int] = (255, 255, 255, 235)
    shadow: tuple[int, int, int, int] = (0, 0, 0, 180)
    shadow_offset: tuple[int, int] = (0, 4)
    margin: tuple[int, int] = (80, 80)
    side: str = "left"  # "left" or "right"


def _cover_blur(src: Image.Image, size: tuple[int, int], blur_radius: int) -> Image.Image:
    sw, sh = src.size
    tw, th = size
    scale = max(tw / sw, th / sh)
    nw, nh = int(sw * scale + 0.5), int(sh * scale + 0.5)
    bg = src.resize((nw, nh), Image.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 2
    bg = bg.crop((left, top, left + tw, top + th))
    return bg.filter(ImageFilter.GaussianBlur(radius=blur_radius))


def _contain(src: Image.Image, size: tuple[int, int]) -> tuple[Image.Image, tuple[int, int]]:
    sw, sh = src.size
    tw, th = size
    scale = min(tw / sw, th / sh)
    nw, nh = int(sw * scale + 0.5), int(sh * scale + 0.5)
    img = src.resize((nw, nh), Image.LANCZOS)
    offset = ((tw - nw) // 2, (th - nh) // 2)
    return img, offset


def _resolve_font_path(explicit: str | None) -> str | None:
    if explicit and Path(explicit).exists():
        return explicit
    for c in SERIF_FALLBACKS:
        if Path(c).exists():
            return c
    return None


def _load_font(path: str | None, size: int) -> ImageFont.ImageFont:
    resolved = _resolve_font_path(path)
    if resolved:
        return ImageFont.truetype(resolved, size)
    return ImageFont.load_default(size=size)


def _draw_clock(canvas: Image.Image, style: ClockStyle) -> None:
    if len(style.lines) != len(style.font_sizes):
        raise ValueError("ClockStyle.lines and font_sizes must have the same length")

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    fonts = [_load_font(style.font_path, sz) for sz in style.font_sizes]

    heights: list[int] = []
    for text, font in zip(style.lines, fonts):
        bbox = draw.textbbox((0, 0), text, font=font, anchor="lt")
        heights.append(bbox[3] - bbox[1])
    total_h = sum(heights) + style.line_spacing * (len(style.lines) - 1)

    w, h = canvas.size
    mx, my = style.margin
    if style.side == "right":
        x = w - mx
        anchor = "rt"
    else:
        x = mx
        anchor = "lt"
    y = h - my - total_h

    sx, sy = style.shadow_offset
    for text, font, line_h in zip(style.lines, fonts, heights):
        draw.text((x + sx, y + sy), text, font=font, fill=style.shadow, anchor=anchor)
        draw.text((x, y), text, font=font, fill=style.color, anchor=anchor)
        y += line_h + style.line_spacing

    canvas.alpha_composite(overlay)


def compose(
    image_path: str | Path,
    screen_size: tuple[int, int],
    clock: ClockStyle | None = None,
    blur_radius: int = 40,
) -> Image.Image:
    src = Image.open(image_path).convert("RGB")
    bg = _cover_blur(src, screen_size, blur_radius).convert("RGBA")
    fg, offset = _contain(src, screen_size)
    bg.paste(fg, offset)
    if clock is not None:
        _draw_clock(bg, clock)
    return bg.convert("RGB")
