"""Format C: all-in story, styled like a mobile poker client (original design, play chips only).

Story: deal -> betting -> all in -> showdown with live equity -> board runs out ->
the sweat -> river (flash + shake; confetti when PokerPilot wins) -> payoff line -> end card.
"""
from __future__ import annotations

import bisect
import copy
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

from content.cards import describe_hand, evaluate, hand_name, parse_cards
from content.equity import round_pct
from . import draw as D
from .draw import CX, GOLD, GREEN, H, MUTED, RED, W, WHITE
from .video import El, Timeline, clamp, confetti, ease_out_cubic, end_scene, paste

YELLOW = (255, 225, 77)
CYAN = (120, 220, 255)
TABLE = (70, 250, 930, 1480)          # stadium felt bounds
BOARD_Y, BOARD_W, BOARD_GAP = 724, 120, 12
POT_XY = (CX, 574)
CAPTION_Y = 446
SEATS = {0: (235, 305), 1: (765, 305), 2: (175, 1045), 3: (825, 1045), 4: (300, 1440)}
BET_XY = {0: (300, 480), 1: (700, 480), 2: (345, 935), 3: (655, 935), 4: (520, 1300)}
BADGE_XY = {2: (330, 1045), 3: (670, 1045), 4: (470, 1440), 0: (390, 305), 1: (610, 305)}
BUTTONS = [("Fold", 190), ("Call", 420), ("Raise", 650)]
BUTTON_Y = 1660


def fmt_chips(n: float) -> str:
    return f"{int(round(n)):,}"


# ---------------------------------------------------------------------------
# static art
# ---------------------------------------------------------------------------

def table_base() -> Image.Image:
    img = D.background().convert("RGBA")
    ss = 2
    x0, y0, x1, y1 = TABLE
    layer = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rad = 330
    d.rounded_rectangle((x0 * ss, y0 * ss, x1 * ss, y1 * ss), radius=rad * ss, fill=(24, 27, 32, 255))
    d.rounded_rectangle(((x0 + 8) * ss, (y0 + 8) * ss, (x1 - 8) * ss, (y1 - 8) * ss), radius=(rad - 8) * ss,
                        outline=(60, 66, 76, 255), width=3 * ss)
    inset = 26
    fx0, fy0, fx1, fy1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    fw, fh = (fx1 - fx0) * ss, (fy1 - fy0) * ss
    felt = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    fd = ImageDraw.Draw(felt)
    c0, c1 = (14, 70, 36), (44, 150, 74)
    for i in range(40):
        t = i / 39
        col = tuple(int(c0[k] + (c1[k] - c0[k]) * t) for k in range(3)) + (255,)
        ix, iy = int(fw * 0.5 * t * 0.8), int(fh * 0.5 * t * 0.8)
        fd.ellipse((ix - fw * 0.15, iy - fh * 0.05, fw - ix + fw * 0.15, fh - iy + fh * 0.05), fill=col)
    felt = felt.filter(ImageFilter.GaussianBlur(40))
    mask = Image.new("L", (fw, fh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, fw - 1, fh - 1), radius=(rad - inset) * ss, fill=255)
    layer.paste(felt, (fx0 * ss, fy0 * ss), mask)
    layer = layer.resize((W, H), Image.LANCZOS)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x0 + 6, y0 + 24, x1 - 6, y1 + 30), radius=rad, fill=(0, 0, 0, 190))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(26)))
    img.alpha_composite(layer)
    # faint club watermark + table info
    wm = D.text_sprite("♠ POKERPILOT", 64, (255, 255, 255), "black", shadow=False, stroke=0)
    wm.putalpha(wm.getchannel("A").point(lambda a: a * 22 // 255))
    img.alpha_composite(wm, (CX - wm.width // 2, 962 - wm.height // 2))
    for txt, y in (("No-Limit Hold'em  •  Blinds 50/100", 856), ("Play chips only", 890)):
        t = D.text_sprite(txt, 28, (255, 255, 255), "semibold", shadow=False, stroke=0)
        t.putalpha(t.getchannel("A").point(lambda a: a * 120 // 255))
        img.alpha_composite(t, (CX - t.width // 2, y - t.height // 2))
    # action buttons (decorative, like a real client)
    for label, x in BUTTONS:
        img.alpha_composite(button(label, False), (x - 105, BUTTON_Y - 45))
    return img.convert("RGB")


@lru_cache(maxsize=8)
def button(label: str, active: bool) -> Image.Image:
    fill = (40, 46, 56, 255) if not active else (230, 170, 40, 255)
    b = D.rounded_box(210, 90, 18, fill, outline=(90, 98, 110, 255) if not active else WHITE + (255,), width=3)
    t = D.text_sprite(label, 40, WHITE if not active else (20, 20, 24), "bold", shadow=False, stroke=0)
    b.alpha_composite(t, ((210 - t.width) // 2, (90 - t.height) // 2))
    return b


@lru_cache(maxsize=16)
def avatar(color: tuple, d: int = 104) -> Image.Image:
    """Original default-style avatar: colored disc with a head-and-shoulders silhouette."""
    ss = 3
    D_ = d * ss
    img = Image.new("RGBA", (D_, D_), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dark = tuple(int(c * 0.55) for c in color)
    dr.ellipse((0, 0, D_ - 1, D_ - 1), fill=dark + (255,))
    light = tuple(min(255, int(c * 1.0 + 40)) for c in color)
    sil = Image.new("RGBA", (D_, D_), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sil)
    sd.ellipse((D_ * 0.32, D_ * 0.16, D_ * 0.68, D_ * 0.52), fill=light + (255,))
    sd.ellipse((D_ * 0.14, D_ * 0.56, D_ * 0.86, D_ * 1.15), fill=light + (255,))
    mask = Image.new("L", (D_, D_), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, D_ - 1, D_ - 1), fill=255)
    sil.putalpha(Image.composite(sil.getchannel("A"), Image.new("L", (D_, D_), 0), mask))
    img.alpha_composite(sil)
    dr = ImageDraw.Draw(img)
    dr.ellipse((0, 0, D_ - 1, D_ - 1), outline=(230, 230, 235, 255), width=4 * ss)
    return img.resize((d, d), Image.LANCZOS)


@lru_cache(maxsize=256)
def plate(name: str, stack: str, color: tuple, folded: bool, winner: bool) -> Image.Image:
    w, h = 200, 88
    pad = 30
    img = Image.new("RGBA", (w + 2 * pad, h + 100 + 2 * pad), (0, 0, 0, 0))
    av = avatar(color)
    if winner:
        g = D.glow(w, h + 100, 30, GOLD, spread=pad, strength=230)
        img.alpha_composite(g, (0, 0))
    img.alpha_composite(av, (pad + (w - av.width) // 2, pad))
    box = D.rounded_box(w, h, 16, (16, 19, 24, 245), outline=(GOLD if winner else (70, 78, 90)) + (255,), width=3)
    nm = D.text_sprite(name, 30, WHITE, "semibold", max_w=w - 24, max_lines=1, shadow=False, stroke=0,
                       min_size=18)
    st = D.text_sprite(stack, 32, CYAN, "bold", max_w=w - 20, max_lines=1, shadow=False, stroke=0)
    box.alpha_composite(nm, ((w - nm.width) // 2, -6))
    box.alpha_composite(st, ((w - st.width) // 2, 34))
    img.alpha_composite(box, (pad, pad + 100))
    if folded:
        a = img.getchannel("A").point(lambda v: v * 45 // 100)
        img.putalpha(a)
    return img


def plate_anchor(seat: int) -> tuple[float, float]:
    """Center of the plate sprite so that the name box centers on SEATS[seat]."""
    x, y = SEATS[seat]
    return x, y - 50


@lru_cache(maxsize=64)
def tag(text: str) -> Image.Image:
    col = {"FOLD": (110, 116, 126), "CHECK": (52, 152, 219), "CALL": (52, 152, 219),
           "BUSTED": (90, 90, 96)}.get(text, (225, 60, 50))
    t = D.text_sprite(text, 26, WHITE, "black", shadow=False, stroke=0)
    b = D.rounded_box(t.width - 4, 44, 12, col + (255,))
    b.alpha_composite(t, ((b.width - t.width) // 2, (44 - t.height) // 2))
    return b


@lru_cache(maxsize=64)
def bet_sprite(amount: str) -> Image.Image:
    chip = D.particle_sprites()[0].resize((40, 40), Image.LANCZOS)
    t = D.text_sprite(amount, 28, WHITE, "bold", shadow=False, stroke=0)
    w = chip.width + t.width - 10
    img = Image.new("RGBA", (w + 16, 50), (0, 0, 0, 0))
    img.alpha_composite(D.rounded_box(w + 16, 50, 25, (0, 0, 0, 150)))
    img.alpha_composite(chip, (6, 5))
    img.alpha_composite(t, (chip.width - 2, (50 - t.height) // 2))
    return img


@lru_cache(maxsize=64)
def pot_sprite(amount: str) -> Image.Image:
    a = D.text_sprite("Total Pot", 24, (200, 210, 220), "semibold", shadow=False, stroke=0)
    b = D.text_sprite(amount, 40, WHITE, "black", shadow=False, stroke=0)
    w = max(a.width, b.width) + 10
    img = D.rounded_box(w, 92, 22, (0, 0, 0, 140))
    img.alpha_composite(a, ((w - a.width) // 2, -14))
    img.alpha_composite(b, ((w - b.width) // 2, 22))
    return img


@lru_cache(maxsize=64)
def badge(pct: int, leading: bool) -> Image.Image:
    col = (34, 170, 90) if leading else (200, 55, 50)
    t = D.text_sprite(f"{pct}%", 36, WHITE, "black", shadow=False, stroke=0)
    b = D.rounded_box(t.width + 4, 60, 18, col + (255,), outline=(255, 255, 255, 220), width=3)
    b.alpha_composite(t, ((b.width - t.width) // 2, (60 - t.height) // 2))
    return b


@lru_cache(maxsize=64)
def hand_label(text: str) -> Image.Image:
    t = D.text_sprite(text, 24, WHITE, "semibold", max_w=300, max_lines=1, shadow=False, stroke=0,
                      min_size=16)
    b = D.rounded_box(t.width + 10, 42, 12, (0, 0, 0, 175))
    b.alpha_composite(t, ((b.width - t.width) // 2, (42 - t.height) // 2))
    return b


def caption(text: str, size: int = 62) -> Image.Image:
    return D.text_sprite(text, size, YELLOW, "black", max_w=D.SAFE_W - 20, max_lines=2, stroke=8,
                         line_spacing=1.04)


# ---------------------------------------------------------------------------
# state machine
# ---------------------------------------------------------------------------

class Script:
    def __init__(self, item: dict):
        seats = item["seats"]
        self.state = {
            "stacks": [float(s["stack"]) for s in seats], "bets": [0.0] * 5, "pot": 150.0,
            "folded": [False] * 5, "tags": [None] * 5, "board_n": 0, "showdown": False,
            "equity": None, "winner": None, "labels": False,
        }
        self.state["stacks"][0] -= 0  # blinds are folded into the starting pot for simplicity
        self.times: list[float] = []
        self.snaps: list[dict] = []
        self.flights: list[tuple] = []   # (t0, dur, (x0,y0), (x1,y1), n)
        self.snap(0.0)

    def snap(self, t: float):
        self.times.append(t)
        self.snaps.append(copy.deepcopy(self.state))

    def at(self, t: float) -> dict:
        i = bisect.bisect_right(self.times, t) - 1
        return self.snaps[max(i, 0)]

    def fly(self, t0, a, b, n=3, dur=0.35):
        self.flights.append((t0, dur, a, b, n))


def build_allin(item: dict, handle: str | None) -> Timeline:
    hero, villain, board = item["hero"], item["villain"], item["board"]
    vseat = item["villain_seat"]
    seats = item["seats"]
    hero_c, vil_c, board_c = parse_cards(hero), parse_cards(villain), parse_cards(board)
    sc = Script(item)
    st = sc.state
    tl = Timeline(25.0)
    tl.scene(0, table_base())
    caps: list[tuple[float, str, int]] = [(0.3, item["hook"], 64)]
    table_cards: list[El] = []  # hidden when the end card starts

    # --- deal
    deal_t = 0.25
    card_spot = {s: (SEATS[s][0] + (55 if SEATS[s][0] < CX else -55), SEATS[s][1] - 128) for s in range(4)}
    small_back = D.card_back(52)
    hero_xy = [(SEATS[4][0] - 52, 1262), (SEATS[4][0] + 52, 1262)]
    for s in range(4):
        tl.add(_Deal(small_back, (CX, BOARD_Y), card_spot[s], deal_t + 0.08 * s))
        tl.sound(deal_t + 0.08 * s, "flip", 0.6)
    for i in range(2):
        tl.add(_Deal(D.card_back(140), (CX, BOARD_Y), hero_xy[i], deal_t + 0.35 + 0.1 * i, until=1.25))
        tl.sound(deal_t + 0.35 + 0.1 * i, "flip", 0.6)
    for i, c in enumerate(hero):
        img = D.card_face(c, 140).rotate((-5, 5)[i], resample=Image.BICUBIC, expand=True)
        table_cards.append(tl.add(El(img, *hero_xy[i], 1.25 + 0.1 * i, None, "flip", dur=0.4,
                                     back=D.card_back(140), bob=3)))

    # --- betting
    t = 1.9
    fold_time = {}
    board_xs = _board_xs()

    def reveal(n_from, n_to, t0, step=0.28, slow=False):
        for i in range(n_from, n_to):
            dur = 1.1 if slow else 0.38
            table_cards.append(tl.add(El(D.card_face(board[i], BOARD_W), board_xs[i], BOARD_Y,
                                         t0 + step * (i - n_from), None, "flip", dur=dur,
                                         back=D.card_back(BOARD_W))))
        return t0 + step * (n_to - n_from - 1) + (1.1 if slow else 0.38)

    def collect(t0):
        moved = False
        for s in range(5):
            if st["bets"][s] > 0:
                sc.fly(t0, BET_XY[s], POT_XY)
                st["pot"] += st["bets"][s]
                st["bets"][s] = 0.0
                moved = True
        st["tags"] = [tg if tg in ("FOLD", "ALL IN") else None for tg in st["tags"]]
        sc.snap(t0 + 0.35)
        return t0 + (0.6 if moved else 0.1)

    allin = item["allin_street"]
    streets = item["streets"]
    n_by_street = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}
    for sd in streets:
        name = sd["street"]
        if name != "preflop":
            t = reveal(st["board_n"], n_by_street[name], t)
            st["board_n"] = n_by_street[name]
            sc.snap(t)
            t += 0.35
        for seat, act, amt in sd["actions"]:
            if act == "fold":
                st["folded"][seat] = True
                st["tags"][seat] = "FOLD"
                fold_time[seat] = t
                sc.snap(t)
                t += 0.42
                continue
            if act == "check":
                st["tags"][seat] = "CHECK"
                sc.snap(t)
                t += 0.55
                continue
            add = max(0.0, min(amt - st["bets"][seat], st["stacks"][seat]))
            st["stacks"][seat] -= add
            st["bets"][seat] += add
            label = {"raise": "RAISE", "bet": "BET", "call": "CALL", "allin": "ALL IN"}[act]
            if st["stacks"][seat] <= 0:
                label = "ALL IN"
            st["tags"][seat] = label
            sc.fly(t, SEATS[seat], BET_XY[seat])
            sc.snap(t)
            if seat == 4:
                btn = {"CALL": "Call", "FOLD": "Fold"}.get(label, "Raise")
                x = dict(BUTTONS)[btn]
                tl.add(El(button(btn, True), x, BUTTON_Y, t - 0.15, t + 0.45, "fade", dur=0.1, out=0.15))
            t += 0.75
        # uncalled excess goes back to whoever covered the other player
        if sd is streets[-1]:
            hb, vb = st["bets"][4], st["bets"][vseat]
            if vb > hb:
                st["stacks"][vseat] += vb - hb
                st["bets"][vseat] = hb
            elif hb > vb:
                st["stacks"][4] += hb - vb
                st["bets"][4] = vb
            for s_ in (4, vseat):  # whoever got chips back isn't actually all in
                if st["stacks"][s_] > 0 and st["tags"][s_] == "ALL IN":
                    st["tags"][s_] = "CALL"
            sc.snap(t)
        t = collect(t)

    # --- showdown
    t_show = t + 0.1
    vx, vy = SEATS[vseat]
    for i, c in enumerate(villain):
        table_cards.append(tl.add(El(D.card_face(c, 92), vx - 30 + 60 * i, vy - 112, t_show + 0.1 * i, None,
                                     "flip", dur=0.4, back=D.card_back(92))))
    eq = item["equity"]
    st["showdown"], st["labels"] = True, True
    st["equity"] = round_pct(eq[allin])
    sc.snap(t_show + 0.5)
    caps.append((t_show + 0.3, item["captions"]["showdown"], 60))
    t = t_show + 2.0
    if st["board_n"] < 3:
        t = reveal(0, 3, t)
        st["board_n"] = 3
        st["equity"] = round_pct(eq["flop"])
        sc.snap(t)
        if item["captions"].get("flop"):
            caps.append((t, item["captions"]["flop"], 60))
        t += 1.5
    if st["board_n"] < 4:
        t = reveal(3, 4, t)
        st["board_n"] = 4
        st["equity"] = round_pct(eq["turn"])
        sc.snap(t)
        caps.append((t, item["captions"]["turn"], 60))
        t += 1.5
    caps.append((t, item["captions"]["sweat"], 66))
    for k in range(3):  # heartbeat during the sweat
        tl.sound(t + 0.1 + 0.9 * k, "thump")
    t += 1.6
    t_river = reveal(4, 5, t, slow=True)
    hero_wins = item.get("outcome") == "hero"
    win, lose = (4, vseat) if hero_wins else (vseat, 4)
    st["board_n"] = 5
    st["equity"] = 100 if hero_wins else 0
    sc.snap(t_river)
    tl.punch(t_river, flash=0.45, shake=22)
    if hero_wins:
        tl.add(confetti(t_river + 0.05, CX, BOARD_Y, seed=int(item["hash"][:8], 16), n=56, half_width=300))
    caps.append((t_river, item["captions"]["river"], 120))
    tl.sound(t_river + 0.15, "win" if hero_wins else "sad")
    # pot to the winner
    sc.fly(t_river + 0.9, POT_XY, SEATS[win], n=5, dur=0.5)
    st["stacks"][win] += st["pot"]
    st["pot"] = 0.0
    st["winner"] = win
    st["tags"][lose] = "BUSTED"
    st["tags"][win] = None
    sc.snap(t_river + 1.35)
    caps.append((t_river + 1.6, item["captions"]["after"], 60))
    t_end = t_river + 4.0
    tl.duration = t_end + 3.0
    for el in table_cards:
        el.t1, el.out = t_end, 0.0

    # --- dynamic layers
    tl.add(_Folds(fold_time, card_spot, small_back, vseat, t_show))
    tl.add(_StateLayer(sc, item, hero_c, vil_c, board_c, t_end))
    for i, (t0, text, size) in enumerate(caps):
        t1 = caps[i + 1][0] if i + 1 < len(caps) else t_end
        tl.add(El(caption(text, size), CX, CAPTION_Y, t0, t1, "pop", dur=0.3, out=0.12))
    for t0, dur, a, b, n in sc.flights:  # chips sliding into / out of the pot
        tl.sound(t0, "chips", 0.7)
    end_scene(tl, t_end, handle)
    return tl


def _board_xs():
    total = 5 * BOARD_W + 4 * BOARD_GAP
    left = CX - total / 2 + BOARD_W / 2
    return [left + i * (BOARD_W + BOARD_GAP) for i in range(5)]


class _Deal:
    """A card back flying from the dealer spot to a seat."""

    def __init__(self, img, a, b, t0, dur=0.28, until=None):
        self.img, self.a, self.b, self.t0, self.dur, self.until = img, a, b, t0, dur, until

    def __call__(self, frame, t):
        if t < self.t0 or (self.until is not None and t >= self.until):
            return
        p = ease_out_cubic(clamp((t - self.t0) / self.dur))
        if self.until is None and p >= 1:
            return  # landed; _Folds keeps drawing the small backs
        x = self.a[0] + (self.b[0] - self.a[0]) * p
        y = self.a[1] + (self.b[1] - self.a[1]) * p
        paste(frame, self.img, x, y, clamp(p * 3))


class _Folds:
    """Opponents' face-down cards: visible until they fold (or the villain shows down)."""

    def __init__(self, fold_time, spots, img, vseat, t_show):
        self.fold_time, self.spots, self.img, self.vseat, self.t_show = fold_time, spots, img, vseat, t_show

    def __call__(self, frame, t):
        if t < 0.6 or t >= self.t_show + 4.5 + 30:
            return
        for s, (x, y) in self.spots.items():
            end = self.fold_time.get(s, self.t_show if s == self.vseat else 99)
            if t >= end + 0.25:
                continue
            op = clamp((end + 0.25 - t) / 0.25) if t > end else 1.0
            dy = 40 * clamp((t - end) / 0.25) if t > end else 0
            paste(frame, self.img, x - 14, y - dy, op)
            paste(frame, self.img, x + 14, y + 4 - dy, op)


class _StateLayer:
    def __init__(self, sc: Script, item, hero_c, vil_c, board_c, t_end):
        self.sc, self.item, self.t_end = sc, item, t_end
        self.hero_c, self.vil_c, self.board_c = hero_c, vil_c, board_c
        self.vseat = item["villain_seat"]

    def __call__(self, frame, t):
        if t >= self.t_end:
            return
        s = self.sc.at(t)
        seats = self.item["seats"]
        for i in range(5):
            x, y = plate_anchor(i)
            if i == 4:
                y += 0
            img = plate(seats[i]["name"], fmt_chips(s["stacks"][i]), tuple(seats[i]["color"]), s["folded"][i],
                        s["winner"] == i)
            if i == 4:
                # hero's avatar sits under the big cards: draw plate first, cards are drawn by El later
                pass
            paste(frame, img, x, y)
            tg = s["tags"][i]
            if tg:
                tx, ty = SEATS[i]
                paste(frame, tag(tg), tx, ty - 62)
            if s["bets"][i] > 0:
                paste(frame, bet_sprite(fmt_chips(s["bets"][i])), *BET_XY[i])
        if s["pot"] > 0:
            paste(frame, pot_sprite(fmt_chips(s["pot"])), *POT_XY)
        if s["equity"] is not None:
            he = s["equity"]
            paste(frame, badge(he, he >= 50), *BADGE_XY[4])
            paste(frame, badge(100 - he, he < 50), *BADGE_XY[self.vseat])
        if s["labels"]:
            vis = self.board_c[:s["board_n"]]
            for seat, cards in ((4, self.hero_c), (self.vseat, self.vil_c)):
                if len(vis) >= 3:
                    txt = describe_hand(evaluate(cards + vis))
                else:
                    from content.cards import cards_str
                    nm = hand_name(*cards_str(cards))
                    txt = nm[0].upper() + nm[1:]
                x, y = SEATS[seat]
                lx = min(max(x, 60 + 160), 940 - 160)
                paste(frame, hand_label(txt), lx, y + 70)
        # chip flights
        chip = D.particle_sprites()[0]
        for t0, dur, a, b, n in self.sc.flights:
            for k in range(n):
                tk = t0 + 0.04 * k
                if tk <= t < tk + dur:
                    p = ease_out_cubic((t - tk) / dur)
                    paste(frame, chip, a[0] + (b[0] - a[0]) * p, a[1] + (b[1] - a[1]) * p, 1.0, 0.8)
