"""Card notation, deck helpers and a fast 5-7 card hand evaluator (pure Python).

Card notation: rank + suit, e.g. "As" = ace of spades, "Td" = ten of diamonds.
Internally a card is an int 0..51: rank_index * 4 + suit_index.
"""
from __future__ import annotations

from typing import Iterable, Sequence

RANKS = "23456789TJQKA"
SUITS = "shdc"  # spades, hearts, diamonds, clubs
SUIT_SYMBOL = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
SUIT_NAME = {"s": "spades", "h": "hearts", "d": "diamonds", "c": "clubs"}
RANK_NAME = {
    "2": "Two", "3": "Three", "4": "Four", "5": "Five", "6": "Six", "7": "Seven",
    "8": "Eight", "9": "Nine", "T": "Ten", "J": "Jack", "Q": "Queen", "K": "King", "A": "Ace",
}
RANK_PLURAL = {r: (n + "es" if n == "Six" else n + "s") for r, n in RANK_NAME.items()}
RANK_LABEL = {r: ("10" if r == "T" else r) for r in RANKS}

# Hand categories (score >> 20)
HIGH_CARD, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)
CATEGORY_NAME = [
    "high card", "one pair", "two pair", "three of a kind", "straight",
    "flush", "full house", "four of a kind", "straight flush",
]

FULL_DECK = list(range(52))


def is_valid_card(s: str) -> bool:
    return isinstance(s, str) and len(s) == 2 and s[0] in RANKS and s[1] in SUITS


def parse_card(s: str) -> int:
    if not is_valid_card(s):
        raise ValueError(f"invalid card: {s!r}")
    return RANKS.index(s[0]) * 4 + SUITS.index(s[1])


def parse_cards(cards: Iterable[str]) -> list[int]:
    return [parse_card(c) for c in cards]


def card_str(c: int) -> str:
    return RANKS[c >> 2] + SUITS[c & 3]


def cards_str(cs: Iterable[int]) -> list[str]:
    return [card_str(c) for c in cs]


def rank_of(c: int) -> int:
    return c >> 2


def suit_of(c: int) -> int:
    return c & 3


def remaining_deck(used: Iterable[int]) -> list[int]:
    u = set(used)
    return [c for c in FULL_DECK if c not in u]


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

def _build_straight_table() -> list[int]:
    table = [-1] * 8192
    for mask in range(8192):
        best = -1
        for top in range(12, 3, -1):  # A-high down to 6-high
            window = 0b11111 << (top - 4)
            if mask & window == window:
                best = top
                break
        if best < 0 and (mask & 0b1000000001111) == 0b1000000001111:  # wheel A-2-3-4-5
            best = 3
        table[mask] = best
    return table


STRAIGHT_TOP = _build_straight_table()
POPCOUNT = [bin(m).count("1") for m in range(8192)]


def _pack(cat: int, ranks: Sequence[int]) -> int:
    v = cat
    for i in range(5):
        v = (v << 4) | (ranks[i] if i < len(ranks) else 0)
    return v


def _top_ranks(mask: int, n: int) -> list[int]:
    out = []
    r = 12
    while r >= 0 and len(out) < n:
        if mask >> r & 1:
            out.append(r)
        r -= 1
    return out


def evaluate(cards: Sequence[int]) -> int:
    """Score of the best 5-card hand from 5..7 cards. Higher is better."""
    rc = [0] * 13
    sm = [0, 0, 0, 0]
    for c in cards:
        r = c >> 2
        rc[r] += 1
        sm[c & 3] |= 1 << r
    # A flush in <=7 cards excludes quads and full houses, so check it first.
    for m in sm:
        if POPCOUNT[m] >= 5:
            st = STRAIGHT_TOP[m]
            if st >= 0:
                return _pack(STRAIGHT_FLUSH, [st])
            return _pack(FLUSH, _top_ranks(m, 5))
    quads, trips, pairs, singles = [], [], [], []
    rmask = 0
    for r in range(12, -1, -1):
        n = rc[r]
        if n:
            rmask |= 1 << r
            if n == 4:
                quads.append(r)
            elif n == 3:
                trips.append(r)
            elif n == 2:
                pairs.append(r)
            else:
                singles.append(r)
    if quads:
        q = quads[0]
        kick = max([r for r in range(13) if rc[r] and r != q], default=0)
        return _pack(QUADS, [q, kick])
    if trips and (len(trips) > 1 or pairs):
        t = trips[0]
        p = max(trips[1] if len(trips) > 1 else -1, pairs[0] if pairs else -1)
        return _pack(FULL_HOUSE, [t, p])
    st = STRAIGHT_TOP[rmask]
    if st >= 0:
        return _pack(STRAIGHT, [st])
    if trips:
        return _pack(TRIPS, [trips[0]] + singles[:2])
    if len(pairs) >= 2:
        kick = max(pairs[2] if len(pairs) > 2 else -1, singles[0] if singles else -1)
        return _pack(TWO_PAIR, [pairs[0], pairs[1], max(kick, 0)])
    if pairs:
        return _pack(PAIR, [pairs[0]] + singles[:3])
    return _pack(HIGH_CARD, singles[:5])


def category(score: int) -> int:
    return score >> 20


def hand_name(c1: str, c2: str) -> str:
    """Plain-English starting hand name: 'pocket Kings', 'AK suited', '10-9 offsuit'."""
    r1, r2 = c1[0], c2[0]
    if RANKS.index(r2) > RANKS.index(r1):
        r1, r2 = r2, r1
    if r1 == r2:
        return f"pocket {RANK_PLURAL[r1]}"
    kind = "suited" if c1[1] == c2[1] else "offsuit"
    a, b = RANK_LABEL[r1], RANK_LABEL[r2]
    sep = "-" if (a == "10" or b == "10") else ""
    return f"{a}{sep}{b} {kind}"
