#!/usr/bin/env python3
"""Render profile pictures (1080x1080 PNG) in the same style as the videos.

    python scripts/make_avatar.py            # writes assets/brand/avatar_*.png

All important content sits inside the center circle, since TikTok crops avatars round.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from render import draw as D  # noqa: E402

S = 1080
C = S // 2


def radial_bg(inner=(22, 34, 44), outer=(6, 9, 13)) -> Image.Image:
    img = Image.new("RGB", (S, S), outer)
    d = ImageDraw.Draw(img)
    steps = 60
    for i in range(steps):
        t = i / (steps - 1)
        r = int(C * 1.45 * (1 - t))
        col = tuple(int(outer[k] + (inner[k] - outer[k]) * t) for k in range(3))
        d.ellipse((C - r, C - r, C + r, C + r), fill=col)
    return img.filter(ImageFilter.GaussianBlur(30)).convert("RGBA")


def felt_disc(radius: int) -> Image.Image:
    """Green felt circle with a wood rail and a thin gold inner line."""
    ss = 2
    size = S * ss
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    r = radius * ss
    c = C * ss
    d.ellipse((c - r, c - r, c + r, c + r), fill=(52, 31, 18, 255))
    rf = r - 30 * ss
    c0, c1 = (12, 74, 40), (36, 134, 74)
    for i in range(40):
        t = i / 39
        rr = int(rf * (1 - 0.85 * t))
        col = tuple(int(c0[k] + (c1[k] - c0[k]) * t) for k in range(3)) + (255,)
        d.ellipse((c - rr, c - rr, c + rr, c + rr), fill=col)
    ri = rf - 34 * ss
    d.ellipse((c - ri, c - ri, c + ri, c + ri), outline=(255, 214, 120, 110), width=4 * ss)
    layer = layer.resize((S, S), Image.LANCZOS)
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse((C - radius + 10, C - radius + 26, C + radius - 10, C + radius + 30),
                               fill=(0, 0, 0, 170))
    return Image.alpha_composite(sh.filter(ImageFilter.GaussianBlur(24)), layer)


def gold_ring(img: Image.Image, radius: int, width: int = 14) -> None:
    ring = Image.new("RGBA", (S * 2, S * 2), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((2 * (C - radius), 2 * (C - radius), 2 * (C + radius), 2 * (C + radius)),
                                 outline=D.GOLD + (255,), width=width * 2)
    img.alpha_composite(ring.resize((S, S), Image.LANCZOS))


def paste_center(base: Image.Image, sprite: Image.Image, cx: float, cy: float) -> None:
    base.alpha_composite(sprite, (int(cx - sprite.width / 2), int(cy - sprite.height / 2)))


def avatar_cards() -> Image.Image:
    img = radial_bg()
    img.alpha_composite(felt_disc(470))
    w = 330
    for card, ang, dx in (("As", 12, -105), ("Kh", -12, 105)):
        spr = D.card_face(card, w).rotate(ang, resample=Image.BICUBIC, expand=True)
        paste_center(img, spr, C + dx, C + 18 + abs(ang))
    gold_ring(img, 500)
    return img


def big_chip(radius: int, color=(200, 30, 48)) -> Image.Image:
    ss = 2
    size = S * ss
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c, r = C * ss, radius * ss
    d.ellipse((c - r, c - r, c + r, c + r), fill=color + (255,), outline=(20, 20, 24, 255), width=6 * ss)
    # edge stripes
    for k in range(8):
        a0 = k * 45 - 9
        d.pieslice((c - r + 6 * ss, c - r + 6 * ss, c + r - 6 * ss, c + r - 6 * ss), a0, a0 + 18,
                   fill=(250, 250, 248, 255))
    ri = int(r * 0.78)
    d.ellipse((c - ri, c - ri, c + ri, c + ri), fill=color + (255,))
    d.ellipse((c - ri, c - ri, c + ri, c + ri), outline=(250, 250, 248, 255), width=5 * ss)
    rj = int(r * 0.70)
    for k in range(36):
        a = math.radians(k * 10)
        x, y = c + math.cos(a) * rj, c + math.sin(a) * rj
        d.ellipse((x - 5 * ss, y - 5 * ss, x + 5 * ss, y + 5 * ss), fill=(255, 220, 120, 255))
    img = img.resize((S, S), Image.LANCZOS)
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse((C - radius, C - radius + 24, C + radius, C + radius + 28), fill=(0, 0, 0, 180))
    return Image.alpha_composite(sh.filter(ImageFilter.GaussianBlur(26)), img)


def suit_glyph(glyph: str, size: int, color) -> Image.Image:
    f = D.font("symbol", size)
    pad = 60
    box = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), glyph, font=f, anchor="mm")
    w, h = box[2] - box[0] + 2 * pad, box[3] - box[1] + 2 * pad
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((w / 2, h / 2 + 14), glyph, font=f, fill=(0, 0, 0, 170), anchor="mm")
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(14)))
    ImageDraw.Draw(img).text((w / 2, h / 2), glyph, font=f, fill=color, anchor="mm",
                             stroke_width=max(4, size // 40), stroke_fill=(12, 12, 14))
    return img


def avatar_chip() -> Image.Image:
    img = radial_bg()
    img.alpha_composite(big_chip(430))
    paste_center(img, suit_glyph("♠", 400, (250, 250, 248)), C, C)
    return img


def avatar_spade() -> Image.Image:
    img = radial_bg()
    img.alpha_composite(felt_disc(470))
    paste_center(img, suit_glyph("♠", 560, D.GOLD), C, C - 10)
    gold_ring(img, 500)
    return img


def main() -> int:
    out = ROOT / "assets" / "brand"
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in (("cards", avatar_cards), ("chip", avatar_chip), ("spade", avatar_spade)):
        p = out / f"avatar_{name}.png"
        fn().convert("RGB").save(p, optimize=True)
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
