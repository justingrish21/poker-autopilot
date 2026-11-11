"""Pillow drawing primitives: fonts, outlined text sprites, cards, table, background."""
from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "assets" / "fonts"

W, H = 1080, 1920
# TikTok safe zone: nothing important in top 150px, bottom 350px, right 140px.
SAFE_LEFT, SAFE_RIGHT, SAFE_TOP, SAFE_BOTTOM = 60, W - 140, 150, H - 350
CX = (SAFE_LEFT + SAFE_RIGHT) // 2  # horizontal center of the safe zone (500)
SAFE_W = SAFE_RIGHT - SAFE_LEFT

WHITE = (255, 255, 255)
GOLD = (255, 200, 61)
GREEN = (46, 204, 113)
RED = (231, 76, 60)
BLUE = (52, 152, 219)
MUTED = (170, 182, 196)
DARK = (11, 15, 20)
CARD_RED = (214, 40, 57)
CARD_BLACK = (20, 20, 24)

FONTS = {
    "bold": "Poppins-Bold.ttf",
    "semibold": "Poppins-SemiBold.ttf",
    "black": "Poppins-ExtraBold.ttf",
    "symbol": "DejaVuSans-Bold.ttf",
}
SUIT_CHARS = set("♠♥♦♣✓✗")
SUIT_GLYPH = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}


@lru_cache(maxsize=256)
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / FONTS[name]), size)


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------

def _runs(text: str):
    """Split text into (is_symbol, chunk) runs so suit glyphs use DejaVu."""
    runs, cur, sym = [], "", None
    for ch in text:
        s = ch in SUIT_CHARS
        if sym is None or s == sym:
            cur += ch
        else:
            runs.append((sym, cur))
            cur = ch
        sym = s
    if cur:
        runs.append((sym, cur))
    return runs


def text_width(text: str, f: ImageFont.FreeTypeFont, fs: ImageFont.FreeTypeFont) -> float:
    return sum((fs if s else f).getlength(chunk) for s, chunk in _runs(text))


def wrap(text: str, f, fs, max_w: float) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            trial = (cur + " " + w).strip()
            if text_width(trial, f, fs) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def fit_text(text: str, font_name: str, size: int, max_w: float, max_lines: int, min_size: int = 28):
    """Largest font size <= size where text wraps into max_lines within max_w."""
    while True:
        f, fs = font(font_name, size), font("symbol", int(size * 0.9))
        lines = wrap(text, f, fs, max_w)
        widest = max(text_width(l, f, fs) for l in lines)
        if (len(lines) <= max_lines and widest <= max_w) or size <= min_size:
            return f, fs, lines, size
        size -= 2


def text_sprite(text: str, size: int, color=WHITE, font_name: str = "bold", max_w: float = SAFE_W,
                max_lines: int = 3, align: str = "center", stroke: int | None = None,
                shadow: bool = True, line_spacing: float = 1.12, colors: dict | None = None) -> Image.Image:
    """Render text (auto-wrapped/shrunk) with a dark outline + soft shadow into an RGBA sprite."""
    f, fs, lines, size = fit_text(text, font_name, size, max_w, max_lines)
    stroke = max(3, size // 14) if stroke is None else stroke
    asc, desc = f.getmetrics()
    lh = int(size * line_spacing)
    widths = [text_width(l, f, fs) for l in lines]
    pad = stroke + 16
    w = int(max(widths)) + 2 * pad
    h = lh * (len(lines) - 1) + asc + desc + 2 * pad
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    def draw_lines(d: ImageDraw.ImageDraw, fill, stroke_w, stroke_fill, dy=0):
        for i, line in enumerate(lines):
            lw = widths[i]
            x = pad if align == "left" else (w - lw) / 2
            y = pad + i * lh + dy
            for sym, chunk in _runs(line):
                ff = fs if sym else f
                fill_c = fill
                if colors and not sym and chunk.strip() in colors:
                    fill_c = colors[chunk.strip()]
                yy = y + (asc - ff.getmetrics()[0]) if sym else y
                d.text((x, yy), chunk, font=ff, fill=fill_c, stroke_width=stroke_w, stroke_fill=stroke_fill)
                x += ff.getlength(chunk)

    if shadow:
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw_lines(ImageDraw.Draw(sh), (0, 0, 0, 200), stroke, (0, 0, 0, 200), dy=max(4, size // 18))
        sh = sh.filter(ImageFilter.GaussianBlur(max(3, size // 16)))
        img = Image.alpha_composite(img, sh)
    d = ImageDraw.Draw(img)
    draw_lines(d, color, stroke, (8, 10, 14, 255))
    return img


def setup_text(text: str) -> str:
    """'100bb cash  |  You: Button' -> '100bb cash  •  You: Button'."""
    return re.sub(r"\s*\|\s*", "  \u2022  ", text.strip())


def pill(text: str, size: int, fg=WHITE, bg=(0, 0, 0, 170), font_name: str = "semibold",
         max_w: float = SAFE_W, pad_x: int = 34, pad_y: int = 16, max_lines: int = 2,
         border=None, prefer_one_line_min: int = 30) -> Image.Image:
    text = setup_text(text)
    inner = max_w - 2 * pad_x
    _, _, lines, fitted = fit_text(text, font_name, size, inner, 1, min_size=prefer_one_line_min)
    if len(lines) == 1 and text_width(lines[0], font(font_name, fitted), font("symbol", int(fitted * 0.9))) <= inner:
        size, max_lines = fitted, 1
    t = text_sprite(text, size, fg, font_name, inner, max_lines, shadow=False, stroke=0)
    tw, th = t.size
    w, h = min(int(max_w), tw + 2 * pad_x - 32), th + 2 * pad_y - 32
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=min(h // 2, 44), fill=bg,
                        outline=border, width=3 if border else 0)
    img.alpha_composite(t, ((w - tw) // 2, (h - th) // 2))
    return img


# ---------------------------------------------------------------------------
# shapes
# ---------------------------------------------------------------------------

def rounded_box(w: int, h: int, radius: int, fill, outline=None, width: int = 0, ss: int = 2) -> Image.Image:
    big = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=radius * ss, fill=fill,
                                          outline=outline, width=width * ss)
    return big.resize((w, h), Image.LANCZOS)


def glow(w: int, h: int, radius: int, color, spread: int = 36, strength: int = 230) -> Image.Image:
    img = Image.new("RGBA", (w + 2 * spread, h + 2 * spread), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((spread, spread, spread + w, spread + h), radius=radius,
                                          fill=color + (strength,))
    return img.filter(ImageFilter.GaussianBlur(spread / 2.2))


def up_arrow(w: int, h: int, color=GOLD) -> Image.Image:
    """Chunky upward arrow drawn as a polygon (emoji fonts don't render)."""
    ss = 3
    img = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    W_, H_ = w * ss, h * ss
    shaft = W_ * 0.36
    head_h = H_ * 0.52
    pts = [(W_ / 2, 0), (W_, head_h), (W_ / 2 + shaft / 2, head_h), (W_ / 2 + shaft / 2, H_),
           (W_ / 2 - shaft / 2, H_), (W_ / 2 - shaft / 2, head_h), (0, head_h)]
    d.polygon(pts, fill=(8, 10, 14, 255))
    inset = 7 * ss
    # inner arrow slightly smaller = dark outline effect
    cx = W_ / 2
    sc = lambda p: (cx + (p[0] - cx) * (1 - 2 * inset / W_), inset + p[1] * (1 - 2 * inset / H_))
    d.polygon([sc(p) for p in pts], fill=color + (255,))
    return img.resize((w, h), Image.LANCZOS)


# ---------------------------------------------------------------------------
# cards
# ---------------------------------------------------------------------------

@lru_cache(maxsize=128)
def card_face(card: str, w: int) -> Image.Image:
    """White rounded card with rank + suit; includes a soft drop shadow."""
    h = int(w * 1.4)
    ss = 2
    cw, ch = w * ss, h * ss
    rank, suit = card[0], card[1]
    color = CARD_RED if suit in "hd" else CARD_BLACK
    label = "10" if rank == "T" else rank
    face = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(face)
    r = int(cw * 0.1)
    d.rounded_rectangle((0, 0, cw - 1, ch - 1), radius=r, fill=(250, 250, 248, 255),
                        outline=(205, 205, 210, 255), width=max(2, cw // 90))
    rf = font("bold", int(cw * (0.36 if label == "10" else 0.42)))
    tx, ty = int(cw * 0.09), int(ch * 0.02)
    d.text((tx, ty), label, font=rf, fill=color)
    sf = font("symbol", int(cw * 0.26))
    rb = d.textbbox((tx, ty), label, font=rf)
    d.text((tx + (rb[2] - rb[0]) / 2 - sf.getlength(SUIT_GLYPH[suit]) / 2, rb[3] + ch * 0.01),
           SUIT_GLYPH[suit], font=sf, fill=color)
    big = font("symbol", int(cw * 0.62))
    g = SUIT_GLYPH[suit]
    bb = d.textbbox((0, 0), g, font=big)
    d.text((cw * 0.56 - (bb[2] - bb[0]) / 2 - bb[0], ch * 0.60 - (bb[3] - bb[1]) / 2 - bb[1]), g,
           font=big, fill=color)
    face = face.resize((w, h), Image.LANCZOS)
    return _with_shadow(face)


@lru_cache(maxsize=8)
def card_back(w: int) -> Image.Image:
    h = int(w * 1.4)
    ss = 2
    cw, ch = w * ss, h * ss
    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(cw * 0.1)
    d.rounded_rectangle((0, 0, cw - 1, ch - 1), radius=r, fill=(250, 250, 248, 255))
    m = int(cw * 0.07)
    d.rounded_rectangle((m, m, cw - m, ch - m), radius=int(r * 0.7), fill=(170, 28, 44, 255))
    pat = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pat)
    step = max(10, cw // 9)
    for k in range(-ch, cw + ch, step):
        pd.line((k, 0, k + ch, ch), fill=(255, 255, 255, 60), width=max(2, cw // 60))
        pd.line((k + ch, 0, k, ch), fill=(255, 255, 255, 60), width=max(2, cw // 60))
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle((m, m, cw - m, ch - m), radius=int(r * 0.7), fill=255)
    pat.putalpha(ImageChops.multiply(pat.getchannel("A"), mask))
    img.alpha_composite(pat)
    img = img.resize((w, h), Image.LANCZOS)
    return _with_shadow(img)


SHADOW_PAD = 22


def _with_shadow(img: Image.Image) -> Image.Image:
    w, h = img.size
    p = SHADOW_PAD
    out = Image.new("RGBA", (w + 2 * p, h + 2 * p), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((p + 4, p + 10, p + w + 4, p + h + 10), radius=int(w * 0.1),
                                         fill=(0, 0, 0, 150))
    out = Image.alpha_composite(out, sh.filter(ImageFilter.GaussianBlur(9)))
    out.alpha_composite(img, (p, p))
    return out


# ---------------------------------------------------------------------------
# background + table
# ---------------------------------------------------------------------------

@lru_cache(maxsize=2)
def background() -> Image.Image:
    """Dark vertical gradient with a subtle vignette and faint suit watermark."""
    top, bottom = (14, 20, 28), (6, 9, 13)
    grad = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / (H - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    img = grad.resize((W, H)).convert("RGBA")
    # faint radial highlight behind the content area
    hl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(hl).ellipse((CX - 620, 260, CX + 620, 1500), fill=(40, 70, 60, 70))
    img = Image.alpha_composite(img, hl.filter(ImageFilter.GaussianBlur(160)))
    # sparse suit watermark
    wm = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(wm)
    f = font("symbol", 120)
    glyphs = "♠♥♦♣"
    for i, (x, y) in enumerate([(40, 300), (880, 520), (90, 1380), (860, 1250), (480, 1700), (700, 170)]):
        d.text((x, y), glyphs[i % 4], font=f, fill=(255, 255, 255, 10))
    img = Image.alpha_composite(img, wm)
    return img.convert("RGB")


def table_layer(cx: int, cy: int, tw: int, th: int) -> Image.Image:
    """Green felt oval with a dark rail, as an RGBA layer the size of the frame."""
    ss = 2
    layer = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = (cx - tw // 2) * ss, (cy - th // 2) * ss, (cx + tw // 2) * ss, (cy + th // 2) * ss
    rail = 26 * ss
    d.ellipse((x0, y0, x1, y1), fill=(52, 31, 18, 255))  # wood rail
    d.ellipse((x0 + 6 * ss, y0 + 6 * ss, x1 - 6 * ss, y1 - 6 * ss), outline=(92, 58, 34, 255), width=4 * ss)
    # felt with radial gradient
    felt_box = (x0 + rail, y0 + rail, x1 - rail, y1 - rail)
    fw, fh = felt_box[2] - felt_box[0], felt_box[3] - felt_box[1]
    felt = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    steps = 40
    fd = ImageDraw.Draw(felt)
    c0, c1 = (12, 74, 40), (33, 128, 70)
    for i in range(steps):
        t = i / (steps - 1)
        col = tuple(int(c0[k] + (c1[k] - c0[k]) * t) for k in range(3)) + (255,)
        ix, iy = int(fw * 0.5 * t * 0.85), int(fh * 0.5 * t * 0.85)
        fd.ellipse((ix, iy, fw - ix, fh - iy), fill=col)
    felt = felt.filter(ImageFilter.GaussianBlur(30))
    mask = Image.new("L", (fw, fh), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, fw - 1, fh - 1), fill=255)
    layer.paste(felt, (felt_box[0], felt_box[1]), mask)
    # inner betting line
    inset = 46 * ss
    d.ellipse((felt_box[0] + inset, felt_box[1] + inset, felt_box[2] - inset, felt_box[3] - inset),
              outline=(255, 214, 120, 70), width=3 * ss)
    layer = layer.resize((W, H), Image.LANCZOS)
    # drop shadow under the table
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse((cx - tw // 2 + 10, cy - th // 2 + 30, cx + tw // 2 - 10, cy + th // 2 + 40),
                               fill=(0, 0, 0, 170))
    sh = sh.filter(ImageFilter.GaussianBlur(28))
    return Image.alpha_composite(sh, layer)


def chip_stack(n: int, color=(220, 50, 60), w: int = 90) -> Image.Image:
    """A simple stack of poker chips (used when a quiz has no cards)."""
    ch = int(w * 0.32)
    step = int(w * 0.13)
    h = ch + step * (n - 1) + 30
    img = Image.new("RGBA", (w + 20, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(n):
        y = h - ch - i * step - 10
        d.ellipse((10, y + 6, 10 + w, y + ch + 6), fill=(0, 0, 0, 90))
        d.ellipse((10, y, 10 + w, y + ch), fill=color + (255,), outline=(20, 20, 20, 255), width=2)
        for k in range(6):
            a = k * math.pi / 3
            px = 10 + w / 2 + math.cos(a) * w * 0.38
            py = y + ch / 2 + math.sin(a) * ch * 0.38
            d.ellipse((px - 5, py - 3, px + 5, py + 3), fill=(255, 255, 255, 230))
        d.ellipse((10 + w * 0.25, y + ch * 0.25, 10 + w * 0.75, y + ch * 0.75), outline=(255, 255, 255, 160), width=2)
    return img


@lru_cache(maxsize=1)
def particle_sprites() -> tuple:
    """Small chips and suit symbols for confetti bursts."""
    out = []
    for col in [(220, 50, 60), (40, 110, 220), (30, 30, 34), (46, 204, 113), (255, 200, 61)]:
        sz = 46
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((2, 2, sz - 3, sz - 3), fill=col + (255,), outline=(255, 255, 255, 255), width=3)
        d.ellipse((13, 13, sz - 14, sz - 14), outline=(255, 255, 255, 200), width=3)
        out.append(img)
    for g, col in [("\u2660", WHITE), ("\u2665", CARD_RED), ("\u2666", CARD_RED), ("\u2663", WHITE), ("\u2665", GOLD)]:
        f = font("symbol", 52)
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((32, 32), g, font=f, fill=col, anchor="mm", stroke_width=3, stroke_fill=(10, 10, 12))
        out.append(img)
    return tuple(out)
