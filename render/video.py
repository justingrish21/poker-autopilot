"""Timeline-based video renderer: Pillow frames piped into ffmpeg (no moviepy)."""
from __future__ import annotations

import math
import os
import random
import subprocess
from pathlib import Path
from typing import Callable

from PIL import Image, ImageChops, ImageDraw

from . import draw as D
from .draw import CX, GOLD, GREEN, H, MUTED, RED, BLUE, W, WHITE

FPS = 30
ROOT = Path(__file__).resolve().parent.parent
MUSIC_DIR = ROOT / "music"
AUDIO_EXTS = {".mp3", ".wav"}


# ---------------------------------------------------------------------------
# easing + compositing helpers
# ---------------------------------------------------------------------------

def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def ease_out_cubic(p):
    return 1 - (1 - p) ** 3


def ease_out_back(p, s=1.7):
    p -= 1
    return 1 + (s + 1) * p ** 3 + s * p ** 2


_alpha_lut = {}
_scaled = {}


def _faded_mask(img: Image.Image, op: float):
    q = int(op * 40)
    key = (id(img), q)
    m = _alpha_lut.get(key)
    if m is None:
        f = q / 40
        m = img.getchannel("A").point([int(a * f) for a in range(256)])
        _alpha_lut[key] = m
    return m


def _scaled_img(img: Image.Image, sx: float, sy: float):
    key = (id(img), round(sx, 2), round(sy, 2))
    s = _scaled.get(key)
    if s is None:
        w = max(1, int(img.width * round(sx, 2)))
        h = max(1, int(img.height * round(sy, 2)))
        s = img.resize((w, h), Image.BILINEAR)
        _scaled[key] = s
    return s


def paste(frame: Image.Image, img: Image.Image, cx: float, cy: float, opacity: float = 1.0,
          sx: float = 1.0, sy: float | None = None):
    if opacity <= 0.01:
        return
    sy = sx if sy is None else sy
    if abs(sx - 1) > 0.005 or abs(sy - 1) > 0.005:
        img = _scaled_img(img, sx, sy)
    x, y = int(cx - img.width / 2), int(cy - img.height / 2)
    if opacity >= 0.99:
        frame.paste(img, (x, y), img)
    else:
        frame.paste(img, (x, y), _faded_mask(img, opacity))


# ---------------------------------------------------------------------------
# elements
# ---------------------------------------------------------------------------

class El:
    """An animated sprite. anim: fade | pop | slide | flip | pulse."""

    def __init__(self, img, cx, cy, t0, t1=None, anim="fade", dur=0.35, out=0.25,
                 slide=(0, 0), back=None, pulse_amp=0.06, pulse_hz=1.6, opacity=1.0,
                 opacity_fn: Callable[[float], float] | None = None, bob=0.0):
        self.img, self.cx, self.cy, self.t0, self.t1 = img, cx, cy, t0, t1
        self.anim, self.dur, self.out, self.slide, self.back = anim, dur, out, slide, back
        self.pulse_amp, self.pulse_hz, self.opacity, self.opacity_fn, self.bob = (
            pulse_amp, pulse_hz, opacity, opacity_fn, bob)

    def __call__(self, frame, t):
        if t < self.t0 or (self.t1 is not None and t >= self.t1):
            return
        p = clamp((t - self.t0) / self.dur) if self.dur > 0 else 1.0
        op = self.opacity
        if self.t1 is not None and self.out > 0:
            op *= clamp((self.t1 - t) / self.out)
        if self.opacity_fn:
            op *= self.opacity_fn(t - self.t0)
        cx, cy, s = self.cx, self.cy, 1.0
        if self.bob:
            cy += math.sin((t - self.t0) * 2 * math.pi * 1.2) * self.bob
        if self.anim == "fade":
            e = ease_out_cubic(p)
            op *= e
            cx += self.slide[0] * (1 - e)
            cy += self.slide[1] * (1 - e)
        elif self.anim == "pop":
            op *= clamp(p * 2.5)
            s = 0.55 + 0.45 * ease_out_back(p)
        elif self.anim == "slide":
            e = ease_out_cubic(p)
            op *= clamp(p * 2)
            cx += self.slide[0] * (1 - e)
            cy += self.slide[1] * (1 - e)
        elif self.anim == "pulse":
            op *= clamp(p * 2.5)
            s = (0.55 + 0.45 * ease_out_back(p)) * (1 + self.pulse_amp * math.sin((t - self.t0) * 2 * math.pi * self.pulse_hz))
        elif self.anim == "flip":
            if p < 1:
                k = abs(math.cos(math.pi * p))
                lift = 1 + 0.10 * math.sin(math.pi * p)
                src = self.back if p < 0.5 else self.img
                paste(frame, src, cx, cy - 18 * math.sin(math.pi * p), op * clamp(p * 4),
                      sx=max(0.02, k) * lift, sy=lift)
                return
        paste(frame, self.img, cx, cy, op, s)


class Timeline:
    def __init__(self, duration: float):
        self.duration = duration
        self.scenes: list[tuple[float, Image.Image]] = []  # (start, RGB base)
        self.layers: list[Callable] = []
        self.xfade = 0.35
        self.flashes: list[tuple[float, float, float]] = []
        self.shakes: list[tuple[float, float, float]] = []

    def scene(self, t0: float, base: Image.Image):
        self.scenes.append((t0, base))

    def add(self, layer):
        self.layers.append(layer)
        return layer

    def base_at(self, t):
        cur, prev, start = None, None, 0.0
        for s, img in self.scenes:
            if t >= s:
                prev, cur, start = cur, img, s
        if prev is not None and t - start < self.xfade:
            return Image.blend(prev, cur, ease_out_cubic((t - start) / self.xfade))
        return cur.copy()

    def frame(self, t):
        f = self.base_at(t)
        for layer in self.layers:
            layer(f, t)
        for t0, dur, strength in self.flashes:
            if t0 <= t < t0 + dur:
                a = strength * (1 - (t - t0) / dur)
                f = Image.blend(f, Image.new("RGB", f.size, (255, 255, 255)), a)
        for t0, dur, amp in self.shakes:
            if t0 <= t < t0 + dur:
                k = amp * (1 - (t - t0) / dur)
                dx = int(k * math.sin((t - t0) * 95))
                dy = int(k * 0.6 * math.cos((t - t0) * 77))
                f = ImageChops.offset(f, dx, dy)
        return f

    def punch(self, t0: float, flash: float = 0.35, shake: float = 14):
        """Reveal impact: quick white flash + screen shake."""
        if flash:
            self.flashes.append((t0, 0.18, flash))
        if shake:
            self.shakes.append((t0, 0.3, shake))


def confetti(t0: float, cx: float, cy: float, seed: int, n: int = 46, dur: float = 2.2, spread: float = 1.0,
             half_width: float = 0):
    """Two bursts of poker chips and suit symbols fired outward from both ends of a
    banner/button (cx +/- half_width), so the revealed text itself stays readable."""
    rng = random.Random(seed)
    sprites = D.particle_sprites()
    parts = []
    for i in range(n):
        side = -1 if i % 2 == 0 else 1
        ang = rng.uniform(-math.pi * 0.92, -math.pi * 0.55) if side < 0 else rng.uniform(-math.pi * 0.45, -math.pi * 0.08)
        speed = rng.uniform(650, 1400) * spread
        parts.append((rng.choice(sprites), math.cos(ang) * speed, math.sin(ang) * speed,
                      rng.uniform(0.75, 1.25), side * half_width))
    g = 2200

    def layer(frame, t):
        dt = t - t0
        if dt < 0 or dt > dur:
            return
        for img, vx, vy, sc, x0 in parts:
            x = cx + x0 + vx * dt
            y = cy + vy * dt + 0.5 * g * dt * dt
            if y > H + 60:
                continue
            op = clamp((dur - dt) / (dur * 0.35))
            paste(frame, img, x, y, op, sc)
    return layer


def progress_bar(duration):
    x0, x1, y, h = D.SAFE_LEFT, D.SAFE_RIGHT, 164, 10

    def layer(frame, t):
        d = ImageDraw.Draw(frame)
        d.rounded_rectangle((x0, y, x1, y + h), radius=h // 2, fill=(40, 48, 58))
        xe = x0 + (x1 - x0) * clamp(t / duration)
        if xe > x0 + h:
            d.rounded_rectangle((x0, y, int(xe), y + h), radius=h // 2, fill=GOLD)
    return layer


# ---------------------------------------------------------------------------
# shared pieces
# ---------------------------------------------------------------------------

def row_positions(n, w, gap, cx=CX):
    total = n * w + (n - 1) * gap
    left = cx - total / 2 + w / 2
    return [left + i * (w + gap) for i in range(n)]


def dark_layer(alpha=0.82):
    return Image.blend(D.background(), Image.new("RGB", (W, H), (0, 0, 0)), alpha)


def with_table(cy, tw, th, darken: float = 0.0) -> Image.Image:
    base = D.background().convert("RGBA")
    base.alpha_composite(D.table_layer(CX, cy, tw, th))
    img = base.convert("RGB")
    if darken:
        img = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), darken)
    return img


BREAKDOWN_TAGS = ["HAND BREAKDOWN", "WHAT WOULD YOU DO?", "STRATEGY BREAKDOWN", "REAL SPOT"]
QUIZ_TAGS = ["POKER QUIZ", "QUICK QUIZ", "TEST YOUR GAME", "PRO LEVEL QUIZ"]
END_CTA = "Play for chips with the link in my bio"
END_LINE = "Practice these spots with real players."


def pick(seq, item, salt=""):
    h = int(item["hash"], 16) if item.get("hash") else 0
    return seq[(h + len(salt)) % len(seq)]


def hook_scene(tl: Timeline, tag: str, hook: str, hero: list[str], t_end: float):
    tl.add(El(D.pill(tag, 40, GOLD, (0, 0, 0, 150), "bold", border=GOLD + (255,)), CX, 520, 0.05, t_end, "pop"))
    hk = D.text_sprite(hook, 112, WHITE, "black", max_w=D.SAFE_W - 10, max_lines=4, line_spacing=1.05)
    tl.add(El(hk, CX, 790, 0.2, t_end, "pop", dur=0.45))
    tl.punch(0.3, flash=0, shake=9)
    if len(hero) == 2:
        w = 150
        for i, (c, ang) in enumerate(zip(hero, (-9, 9))):
            img = D.card_face(c, w).rotate(-ang, resample=Image.BICUBIC, expand=True)
            tl.add(El(img, CX + (i - 0.5) * 120, 1200 + (abs(ang) * 1.2), 0.5 + i * 0.12, t_end,
                      "slide", dur=0.45, slide=(0, 260)))


def end_scene(tl: Timeline, t0: float, handle: str | None):
    tl.scene(t0, D.background())
    for i, (c, ang) in enumerate(zip(("As", "Kh"), (-10, 10))):
        img = D.card_face(c, 130).rotate(-ang, resample=Image.BICUBIC, expand=True)
        tl.add(El(img, CX + (i - 0.5) * 110, 345 + abs(ang), t0 + 0.05 + 0.1 * i, None, "pop"))
    tl.add(El(D.text_sprite("Want to play?", 104, WHITE, "black", max_lines=2), CX, 600, t0 + 0.15, None, "pop"))
    tl.add(El(D.text_sprite(END_CTA, 80, GOLD, "black", max_lines=2, line_spacing=1.05), CX, 800,
              t0 + 0.45, None, "pulse", pulse_amp=0.03, pulse_hz=1.2))
    tl.add(El(D.up_arrow(120, 150), CX, 1010, t0 + 0.8, None, "pop", bob=16))
    y = 1160
    if handle:
        h = handle if handle.startswith("@") else "@" + handle
        tl.add(El(D.text_sprite(h, 52, MUTED, "semibold", max_lines=1), CX, y, t0 + 1.1, None, "fade"))
        y += 90
    tl.add(El(D.text_sprite(END_LINE, 46, WHITE, "bold", max_lines=1), CX, y, t0 + 1.3, None, "pop"))


def play_color(play: str):
    p = play.upper()
    if "FOLD" in p:
        return RED
    if p.startswith(("CALL", "JUST CALL", "CHECK")):
        return BLUE
    if any(k in p for k in ("RAISE", "BET", "ALL IN", "SHOVE", "3-BET", "4-BET")):
        return GREEN
    return (232, 160, 32)


def banner(text: str, color, size=92):
    t = D.text_sprite(text, size, WHITE, "black", max_w=D.SAFE_W - 80, max_lines=2, shadow=False)
    w = min(D.SAFE_W, t.width + 40)
    h = t.height + 10
    img = D.rounded_box(w, h, 34, color + (255,), outline=(255, 255, 255, 230), width=5)
    g = D.glow(w, h, 34, color, spread=40, strength=150)
    out = Image.new("RGBA", g.size, (0, 0, 0, 0))
    out.alpha_composite(g)
    out.alpha_composite(img, (40, 40))
    out.alpha_composite(t, (40 + (w - t.width) // 2, 40 + (h - t.height) // 2))
    return out


def reason_sprite(i: int, text: str, size: int):
    badge = 76
    t = D.text_sprite(text, size, WHITE, "semibold", max_w=D.SAFE_W - badge - 40, max_lines=3,
                      align="left", stroke=3)
    h = max(t.height, badge + 20)
    img = Image.new("RGBA", (D.SAFE_W, h), (0, 0, 0, 0))
    b = D.rounded_box(badge, badge, badge // 2, GOLD + (255,))
    n = D.text_sprite(str(i + 1), 46, (20, 20, 24), "black", shadow=False, stroke=0)
    b.alpha_composite(n, ((badge - n.width) // 2, (badge - n.height) // 2 + 2))
    img.alpha_composite(b, (0, (h - badge) // 2))
    img.alpha_composite(t, (badge + 14, (h - t.height) // 2))
    return img


def option_button(letter: str, text: str, state: str = "normal"):
    w, h = D.SAFE_W, 112
    fill = {"normal": (24, 34, 46, 245), "correct": (22, 92, 54, 255)}[state]
    border = {"normal": (90, 104, 120, 255), "correct": GREEN + (255,)}[state]
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    img.alpha_composite(D.rounded_box(w, h, 30, fill, outline=border, width=4))
    bw = 78
    badge = D.rounded_box(bw, bw, bw // 2, (GREEN if state == "correct" else GOLD) + (255,))
    lt = D.text_sprite(letter, 44, (16, 18, 22), "black", shadow=False, stroke=0)
    badge.alpha_composite(lt, ((bw - lt.width) // 2, (bw - lt.height) // 2 + 2))
    img.alpha_composite(badge, (18, (h - bw) // 2))
    t = D.text_sprite(text, 50, WHITE, "bold", max_w=w - bw - 130, max_lines=1, align="left", stroke=3,
                      shadow=False)
    img.alpha_composite(t, (bw + 30, (h - t.height) // 2))
    if state == "correct":
        ck = D.text_sprite("✓", 64, WHITE, "bold", shadow=False, stroke=0)
        img.alpha_composite(ck, (w - ck.width - 16, (h - ck.height) // 2))
    return img


def cards_on_table(tl: Timeline, item: dict, t0: float, board_y: int, hero_y: int, villain_y: int,
                   board_w: int, hero_w: int, villain_w: int, t1: float, board_step: float = 0.4,
                   solo_hero_y: int | None = None, solo_hero_w: int | None = None) -> float:
    """Animate villain (flip), hero (slide) and board (flip one at a time). Returns end time."""
    hero, board, villain = item.get("hero", []), item.get("board", []), item.get("villain", [])
    t = t0
    if villain:
        lbl = D.text_sprite("VILLAIN", 30, MUTED, "bold", stroke=2, shadow=False)
        vh = int(villain_w * 1.4)
        tl.add(El(lbl, CX, villain_y - vh / 2 - 30, t, t1, "fade"))
        for i, (c, x) in enumerate(zip(villain, row_positions(2, villain_w, 14))):
            tl.add(El(D.card_face(c, villain_w), x, villain_y, t + 0.12 * i, t1, "flip", dur=0.4,
                      back=D.card_back(villain_w)))
        t += 0.35
    if hero:
        hy, hw = hero_y, hero_w
        if not board and not villain and solo_hero_y:
            hy, hw = solo_hero_y, solo_hero_w or hero_w
        for i, (c, x) in enumerate(zip(hero, row_positions(2, hw, 18))):
            tl.add(El(D.card_face(c, hw), x, hy, t + 0.15 * i, t1, "slide", dur=0.5, slide=(0, 700),
                      bob=5))
        t += 0.6
    if board:
        xs = row_positions(5, board_w, 14)
        slot = D.rounded_box(board_w, int(board_w * 1.4), int(board_w * 0.1), (255, 255, 255, 14),
                             outline=(255, 255, 255, 70), width=3)
        for x in xs[len(board):]:
            tl.add(El(slot, x, board_y, t, t1, "fade"))
        for i, (c, x) in enumerate(zip(board, xs)):
            tl.add(El(D.card_face(c, board_w), x, board_y, t + board_step * i, t1, "flip", dur=0.38,
                      back=D.card_back(board_w)))
        t += board_step * len(board)
    return t


# ---------------------------------------------------------------------------
# Format A: breakdown (~22 s)
# ---------------------------------------------------------------------------

def build_breakdown(item: dict, handle: str | None) -> Timeline:
    T = 22.0
    tl = Timeline(T)
    tl.scene(0, D.background())
    hook_scene(tl, item.get("tag") or pick(BREAKDOWN_TAGS, item), item["hook"], item.get("hero", []), 3.0)

    table_cy, tw, th = 860, 860, 720
    tl.scene(3.0, with_table(table_cy, tw, th))
    t_out = 11.0
    tl.add(El(D.pill(item["setup"], 40, WHITE, (0, 0, 0, 175), max_lines=2), CX, 240, 3.15, t_out, "slide",
              slide=(0, -40)))
    villain_y = 640 if item.get("villain") else 0
    board_y = 835 if item.get("villain") else 800
    t_cards = cards_on_table(tl, item, 3.4, board_y=board_y, hero_y=1105, villain_y=villain_y,
                             board_w=130, hero_w=170, villain_w=104, t1=t_out,
                             solo_hero_y=900, solo_hero_w=210)
    t_act = clamp(t_cards + 0.3, 4.6, 7.6)
    act = D.text_sprite(item["action"], 52, WHITE, "bold", max_lines=2)
    tl.add(El(act, CX, 1320, t_act, t_out, "pop"))
    q = D.text_sprite("What's the play?", 80, GOLD, "black", max_lines=1)
    tl.add(El(q, CX, 1440, 9.0, t_out, "pulse", pulse_amp=0.07, pulse_hz=2.0))
    tl.add(El(D.text_sprite("Comment what you'd do", 38, WHITE, "semibold", max_lines=1), CX, 1525, 9.3,
              t_out, "fade", slide=(0, 20)))

    # verdict
    tl.scene(t_out, with_table(table_cy, tw, th, darken=0.84))
    t_end = 19.0
    tl.add(El(D.text_sprite("THE PLAY:", 54, GOLD, "black"), CX, 300, 11.15, t_end, "fade", slide=(0, 20)))
    bn = banner(item["play"], play_color(item["play"]))
    tl.add(El(bn, CX, 430, 11.3, t_end, "pop", dur=0.5))
    tl.punch(11.3, flash=0.3, shake=14)
    tl.add(confetti(11.3, CX, 430, seed=int(item["hash"][:8], 16), n=36, half_width=bn.width / 2 - 70))
    why = item["why"][:3]
    size = 54
    while True:
        sprites = [reason_sprite(i, r, size) for i, r in enumerate(why)]
        total = sum(s.height for s in sprites) + 34 * (len(sprites) - 1)
        if total <= 1320 - 590 or size <= 38:
            break
        size -= 4
    y = 590 + (1320 - 590 - total) / 2 * 0.4
    starts = [12.3, 14.0, 15.7] if len(why) == 3 else [12.3, 14.6]
    for s, st in zip(sprites, starts):
        tl.add(El(s, CX, y + s.height / 2, st, t_end, "slide", dur=0.5, slide=(-60, 0)))
        y += s.height + 34
    # mini hand reminder
    mini = 84
    hero, board = item.get("hero", []), item.get("board", [])
    cards = hero + ([None] if hero and board else []) + board
    if cards:
        xs = row_positions(len(cards), mini, 8)
        for c, x in zip(cards, xs):
            if c:
                tl.add(El(D.card_face(c, mini), x, 1455, 11.8, t_end, "fade"))
    end_scene(tl, t_end, handle)
    tl.add(progress_bar(T))
    return tl


# ---------------------------------------------------------------------------
# Format B: quiz (~18 s)
# ---------------------------------------------------------------------------

def build_quiz(item: dict, handle: str | None) -> Timeline:
    T = 18.0
    tl = Timeline(T)
    tl.scene(0, D.background())
    hook_scene(tl, item.get("tag") or pick(QUIZ_TAGS, item), item.get("hook") or "Can you get this right?",
               item.get("hero", []), 2.0)

    table_cy, tw, th = 790, 860, 580
    tl.scene(2.0, with_table(table_cy, tw, th))
    t_end = 15.0
    tl.add(El(D.text_sprite(item["q"], 60, WHITE, "black", max_lines=3, line_spacing=1.08), CX, 300, 2.1,
              t_end, "pop"))
    tl.add(El(D.pill(item["setup"], 34, GOLD, (0, 0, 0, 175), "bold", max_lines=1), CX, 462, 2.35, t_end, "fade"))

    has_cards = bool(item.get("hero") or item.get("board") or item.get("villain"))
    if has_cards:
        villain = bool(item.get("villain"))
        cards_on_table(tl, item, 2.5, board_y=725 if not villain else 790, hero_y=950,
                       villain_y=680, board_w=112, hero_w=140, villain_w=120 if not item.get("board") else 96,
                       t1=t_end, board_step=0.3, solo_hero_y=790, solo_hero_w=180)
    else:
        for i, (dx, n, col) in enumerate([(-170, 5, (220, 50, 60)), (0, 7, (40, 110, 220)), (170, 4, (30, 30, 34))]):
            tl.add(El(D.chip_stack(n, col, 110), CX + dx, 800, 2.5 + 0.15 * i, t_end, "slide", slide=(0, 120)))
        tl.add(El(D.text_sprite("?", 120, GOLD, "black"), CX, 640, 2.9, 7.0, "pulse", pulse_amp=0.08))

    letters = "ABC"
    opt_y = [1170, 1298, 1426]
    opts = item["options"][:3]
    n = len(opts)
    ys = opt_y[:n] if n == 3 else [1234, 1362]
    for i, (o, y) in enumerate(zip(opts, ys)):
        normal = option_button(letters[i], o)
        st = 4.4 + 0.3 * i
        if i == item["answer"]:
            g = D.glow(D.SAFE_W + 16, 128, 36, GREEN, spread=46, strength=255)
            tl.add(El(g, CX, y, 10.0, t_end, "fade", dur=0.3,
                      opacity_fn=lambda dt: 0.65 + 0.35 * math.sin(dt * 2 * math.pi * 1.4)))
            tl.add(El(normal, CX, y, st, 10.0, "slide", slide=(-140, 0), out=0))
            tl.add(El(option_button(letters[i], o, "correct"), CX, y, 10.0, t_end, "pop", dur=0.35))
            correct_y = y
        else:
            tl.add(El(normal, CX, y, st, t_end, "slide", slide=(-140, 0)))
            dim = D.rounded_box(D.SAFE_W, 112, 30, (0, 0, 0, 175))
            tl.add(El(dim, CX, y, 10.0, t_end, "fade", dur=0.3))

    # countdown over a dimmed table
    panel = D.rounded_box(D.SAFE_W, 610, 48, (6, 9, 13, 232))
    tl.add(El(panel, CX, 790, 7.0, t_end, "fade", dur=0.3))
    for k, num in enumerate("321"):
        t0 = 7.0 + k
        tl.add(El(D.text_sprite(num, 280, GOLD, "black", stroke=10), CX, 735, t0, t0 + 1.0, "pop", dur=0.35, out=0.2))
    ring_cx, ring_cy, rr = CX, 735, 175

    def ring(frame, t):
        if 7.0 <= t < 10.0:
            p = (t - 7.0) % 1.0
            d = ImageDraw.Draw(frame)
            d.arc((ring_cx - rr, ring_cy - rr, ring_cx + rr, ring_cy + rr), -90, -90 + 360 * (1 - p),
                  fill=GOLD, width=12)
    tl.add(ring)
    tl.add(El(D.text_sprite("Comment your answer", 56, WHITE, "black", max_lines=1), CX, 990, 7.0, 10.0,
              "pulse", pulse_amp=0.04, pulse_hz=2))

    # reveal
    tl.punch(10.0, flash=0.3, shake=12)
    ans = f"ANSWER: {letters[item['answer']]}"
    tl.add(El(D.text_sprite(ans, 64, GREEN, "black"), CX, 560, 10.05, t_end, "pop"))
    tl.add(El(D.text_sprite(item["explain"], 50, WHITE, "bold", max_w=D.SAFE_W - 70, max_lines=5),
              CX, 800, 10.4, t_end, "fade", slide=(0, 20)))
    tl.add(confetti(10.0, CX, correct_y, seed=int(item["hash"][:8], 16), n=44, half_width=D.SAFE_W / 2 - 20))
    end_scene(tl, t_end, handle)
    tl.add(progress_bar(T))
    return tl


# ---------------------------------------------------------------------------
# encode
# ---------------------------------------------------------------------------

def pick_music(rng: random.Random | None = None) -> Path | None:
    if not MUSIC_DIR.is_dir():
        return None
    files = sorted(p for p in MUSIC_DIR.iterdir() if p.suffix.lower() in AUDIO_EXTS and p.is_file())
    return (rng or random.Random()).choice(files) if files else None


def encode(tl: Timeline, out_path: Path, music: Path | None, music_gain_db: float = -18.0,
           preset: str = "medium") -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    T = tl.duration
    nframes = int(round(T * FPS))
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        # asetpts makes timestamps continuous across loops so the fade-out lands at the end.
        af = (f"aresample=44100,asetpts=N/SR/TB,atrim=0:{T:.3f},volume={music_gain_db}dB,"
              f"afade=t=in:st=0:d=1,afade=t=out:st={T - 1:.3f}:d=1,"
              f"aformat=sample_rates=44100:channel_layouts=stereo")
        cmd += ["-filter:a", af]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    cmd += ["-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", preset, "-crf", "20", "-pix_fmt", "yuv420p",
            "-profile:v", "high", "-r", str(FPS), "-g", str(FPS * 2),
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-t", f"{T:.3f}", "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(nframes):
            proc.stdin.write(tl.frame(i / FPS).tobytes())
    finally:
        proc.stdin.close()
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed with exit code {rc}")


def build_timeline(item: dict, handle: str | None = None) -> Timeline:
    _alpha_lut.clear()  # caches are keyed by id(); never reuse them across videos
    _scaled.clear()
    if item["format"] == "allin":
        from .allin import build_allin
        return build_allin(item, handle)
    return build_breakdown(item, handle) if item["format"] == "breakdown" else build_quiz(item, handle)


def render_item(item: dict, out_path: Path, handle: str | None = None, music: Path | None | bool = True,
                rng: random.Random | None = None) -> dict:
    tl = build_timeline(item, handle)
    track = pick_music(rng) if music is True else (music or None)
    gain = float(os.environ.get("MUSIC_GAIN_DB", "-18"))
    encode(tl, out_path, track, gain)
    return {"path": str(out_path), "duration": tl.duration, "music": track.name if track else None}


def render_stills(item: dict, times: list[float], out_dir: Path, handle: str | None = None) -> list[Path]:
    tl = build_timeline(item, handle)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for t in times:
        p = out_dir / f"{item['id']}_{t:05.2f}.png"
        tl.frame(t).save(p)
        paths.append(p)
    return paths
