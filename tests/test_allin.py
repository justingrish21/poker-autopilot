"""All-in stories (bad beats, suckouts, coolers): verify the math and the chip story."""
from __future__ import annotations

import itertools
import random

import pytest

from content.allin import ALLIN_KINDS, HERO_NAME, gen_allin
from content.cards import evaluate, parse_cards, remaining_deck
from content.library import validate_item
from content.generators import generate
from render.allin import _StateLayer
from render.video import build_timeline
from tests.test_math import naive_best


def brute_equity(hero, villain, board):
    deck = remaining_deck(hero + villain + board)
    score = total = 0
    for run in itertools.combinations(deck, 5 - len(board)):
        full = board + list(run)
        a, b = naive_best(hero + full), naive_best(villain + full)
        score += 2 if a > b else 1 if a == b else 0
        total += 2
    return score / total


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("kind", ALLIN_KINDS)
def test_allin_math(kind, seed):
    it = gen_allin(random.Random(f"t{kind}{seed}"), kind)
    hero, vil, board = parse_cards(it["hero"]), parse_cards(it["villain"]), parse_cards(it["board"])
    hs, vs = naive_best(hero + board), naive_best(vil + board)
    if kind == "badbeat":
        assert vs > hs and it["outcome"] == "villain"
    else:
        assert hs > vs and it["outcome"] == "hero"
    # exact equities match brute force
    assert abs(brute_equity(hero, vil, board[:4]) - it["equity"]["turn"]) < 1e-12
    assert abs(brute_equity(hero, vil, board[:3]) - it["equity"]["flop"]) < 1e-12
    # the river card is one of the listed outs (for the winner), and the out count is right
    deck44 = remaining_deck(hero + vil + board[:4])
    if kind == "cooler":
        expected = [c for c in deck44 if naive_best(vil + board[:4] + [c]) > naive_best(hero + board[:4] + [c])]
        assert board[4] not in expected
    else:
        a, b = (hero, vil) if kind == "suckout" else (vil, hero)
        expected = [c for c in deck44 if naive_best(a + board[:4] + [c]) > naive_best(b + board[:4] + [c])]
        assert board[4] in expected
        fav_turn = it["equity"]["turn"] if kind == "badbeat" else 1 - it["equity"]["turn"]
        assert fav_turn >= 0.75  # the eventual loser really was a big favorite on the turn
    assert it["math"]["n_outs"] == len(expected)
    assert abs(it["math"]["p_out"] - len(expected) / 44) < 1e-12
    assert f"{len(expected) / 44 * 100:.1f}%" in it["captions"]["after"] or kind == "cooler"
    # seats
    names = [s["name"] for s in it["seats"]]
    assert names[4] == HERO_NAME and names.count(HERO_NAME) == 1 and len(set(names)) == 5
    assert validate_item({**it, "format": "allin", "id": "x"}) == []


@pytest.mark.parametrize("n", range(6))
def test_allin_chip_story_and_render(n):
    it = generate("allin", n)
    tl = build_timeline(it, "PokerPilot")
    assert 15 <= tl.duration <= 25
    layer = next(l for l in tl.layers if isinstance(l, _StateLayer))
    first, last = layer.sc.snaps[0], layer.sc.snaps[-1]
    v = it["villain_seat"]
    win, lose = (4, v) if it["outcome"] == "hero" else (v, 4)
    assert last["stacks"][lose] == 0
    assert last["stacks"][win] == first["stacks"][win] + first["stacks"][lose] + first["pot"]
    for s in range(4):
        if s != v:
            assert last["stacks"][s] == first["stacks"][s]  # folders keep their chips
    for t in (1.0, 6.0, tl.duration - 6, tl.duration - 1):
        assert tl.frame(t).size == (1080, 1920)


def test_find_generated_allin_item():
    from content.rotation import find_item
    assert find_item("gen-allin-00004")["format"] == "allin"
