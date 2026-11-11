"""Brute-force checks of the evaluator and every generator's math."""
from __future__ import annotations

import itertools
import random
from collections import Counter
from fractions import Fraction
from math import comb

import pytest

from content.cards import (FLUSH, PAIR, STRAIGHT, card_str, category, evaluate, parse_card, parse_cards,
                           rank_of, remaining_deck, suit_of)
from content.equity import exact_equity, monte_carlo_equity, required_equity
from content.generators import (BREAKDOWN_KINDS, QUIZ_KINDS, count_combos, gen_combos,
                                gen_draw_allin_flop, gen_draw_turn_bet, gen_outs, gen_pot_odds,
                                gen_preflop_equity, gen_rule_2_4, generate)
from content.library import validate_item

SEEDS = range(40)


# --- independent naive evaluator ------------------------------------------------------

def naive5(cards):
    ranks = sorted((rank_of(c) for c in cards), reverse=True)
    suits = [suit_of(c) for c in cards]
    cnt = Counter(ranks)
    groups = sorted(cnt.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    flush = len(set(suits)) == 1
    uniq = sorted(set(ranks), reverse=True)
    straight_top = None
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            straight_top = uniq[0]
        elif uniq == [12, 3, 2, 1, 0]:
            straight_top = 3
    if straight_top is not None and flush:
        return (8, straight_top)
    if groups[0][1] == 4:
        return (7, groups[0][0], groups[1][0])
    if groups[0][1] == 3 and groups[1][1] == 2:
        return (6, groups[0][0], groups[1][0])
    if flush:
        return (5, *ranks)
    if straight_top is not None:
        return (4, straight_top)
    if groups[0][1] == 3:
        return (3, groups[0][0], *[r for r in ranks if r != groups[0][0]])
    if groups[0][1] == 2 and groups[1][1] == 2:
        k = [r for r in ranks if cnt[r] == 1][0]
        return (2, groups[0][0], groups[1][0], k)
    if groups[0][1] == 2:
        return (1, groups[0][0], *[r for r in ranks if r != groups[0][0]])
    return (0, *ranks)


def naive_best(cards):
    return max(naive5(c) for c in itertools.combinations(cards, 5))


def test_evaluator_matches_naive_on_random_hands():
    rng = random.Random(1)
    for _ in range(3000):
        cards = rng.sample(range(52), 7 + 2)
        board, a, b = cards[:5], cards[5:7], cards[7:9]
        ea, eb = evaluate(a + board), evaluate(b + board)
        na, nb = naive_best(a + board), naive_best(b + board)
        assert category(ea) == na[0]
        assert (ea > eb) == (na > nb) and (ea == eb) == (na == nb)


def test_evaluator_known_hands():
    p = lambda s: parse_cards(s.split())
    assert category(evaluate(p("Ah 2d 3c 4s 5h Kd Kc"))) == STRAIGHT  # wheel
    assert evaluate(p("Ah 2d 3c 4s 5h 6d Kc")) > evaluate(p("Ah 2d 3c 4s 5h Kd Kc"))
    assert category(evaluate(p("As Ks Qs Js Ts 2d 2c"))) == 8
    assert category(evaluate(p("Ah Kh 7h 2h 9h 9d 9c"))) == FLUSH


@pytest.mark.parametrize("h,v,expected", [
    ("As Ad", "Kc Kd", 0.82), ("2s 2h", "Ac Kd", 0.525), ("Ah Kh", "Qc Qd", 0.46),
])
def test_monte_carlo_matches_known_equities(h, v, expected):
    eq = monte_carlo_equity(parse_cards(h.split()), parse_cards(v.split()), (), 20000, random.Random(5))
    assert abs(eq - expected) < 0.015


def test_monte_carlo_matches_exact_on_flop():
    hero, vil, board = parse_cards("Ah Kh".split()), parse_cards("Qc Qd".split()), parse_cards("2h 7h Qs".split())
    ex = exact_equity(hero, vil, board)
    mc = monte_carlo_equity(hero, vil, board, 20000, random.Random(2))
    assert abs(ex - mc) < 0.015


# --- generators ---------------------------------------------------------------------

def brute_required(pot, bet):
    """Find break-even equity by scanning EV = e*(pot+bet) - (1-e)*bet over a fine grid."""
    lo = None
    for i in range(100001):
        e = Fraction(i, 100000)
        if e * (pot + bet) - (1 - e) * bet >= 0:
            lo = e
            break
    return float(lo)


@pytest.mark.parametrize("seed", SEEDS)
def test_pot_odds(seed):
    it = gen_pot_odds(random.Random(seed))
    m = it["math"]
    assert abs(brute_required(m["pot"], m["bet"]) - m["required"]) < 1e-4
    assert it["options"][it["answer"]] == f"{int(m['required'] * 100 + 0.5)}%"
    assert len(set(it["options"])) == 3


def brute_outs(hero, board, target):
    deck = remaining_deck(hero + board)
    outs = set()
    for c in deck:
        nb = board + [c]
        s = evaluate(hero + nb)
        if category(s) >= target and (len(nb) < 5 or evaluate(nb) < s):
            outs.add(c)
    return outs


def brute_overcard_outs(hero, board):
    top = max(rank_of(c) for c in board)
    return {c for c in remaining_deck(hero + board)
            if rank_of(c) in {rank_of(h) for h in hero} and rank_of(c) > top}


@pytest.mark.parametrize("seed", SEEDS)
def test_outs(seed):
    it = gen_outs(random.Random(seed))
    hero, board = parse_cards(it["hero"]), parse_cards(it["board"])
    draw = it["math"]["draw"]
    if draw == "overcards":
        expected = brute_overcard_outs(hero, board)
    elif draw == "flush":
        expected = brute_outs(hero, board, FLUSH)
    else:
        expected = brute_outs(hero, board, STRAIGHT)  # straight-or-better: flush cards counted once
    assert set(parse_cards(it["math"]["outs"])) == expected
    assert it["options"][it["answer"]] == str(len(expected))
    # sanity: textbook counts
    textbook = {"flush": {9}, "oesd": {8}, "gutshot": {4}, "overcards": {6}, "combo": {12, 15}}
    assert len(expected) in textbook[draw] or draw == "combo" and 10 <= len(expected) <= 15


@pytest.mark.parametrize("seed", SEEDS)
def test_rule_2_4(seed):
    it = gen_rule_2_4(random.Random(seed))
    m = it["math"]
    hero, board = parse_cards(it["hero"]), parse_cards(it["board"])
    outs = set(parse_cards(m["outs"]))
    deck = remaining_deck(hero + board)
    assert m["unseen"] == len(deck)
    if m["street"] == "flop":
        hits = sum(1 for a, b in itertools.combinations(deck, 2) if a in outs or b in outs)
        exact = hits / comb(len(deck), 2)
        assert m["estimate"] == 4 * len(outs)
    else:
        exact = sum(1 for c in deck if c in outs) / len(deck)
        assert m["estimate"] == 2 * len(outs)
    assert abs(exact - m["exact"]) < 1e-12
    assert f"{exact * 100:.1f}%" in it["explain"]
    assert it["options"][it["answer"]] == f"{m['estimate']}%"


@pytest.mark.parametrize("seed", range(8))
def test_preflop_equity(seed):
    it = gen_preflop_equity(random.Random(seed))
    hero, vil = parse_cards(it["hero"]), parse_cards(it["villain"])
    # independent Monte Carlo with a different seed, larger sample
    eq = monte_carlo_equity(hero, vil, (), 40000, random.Random(999 + seed)) * 100
    lo, hi = (int(x) for x in it["options"][it["answer"]].rstrip("%").split("-"))
    assert lo - 1.0 <= eq <= hi + 1.0
    assert abs(eq - it["math"]["equity"] * 100) < 1.2


def brute_combos(ranks, kind, dead):
    deck = remaining_deck(dead)
    n = 0
    for a, b in itertools.combinations(deck, 2):
        ra, rb = sorted((rank_of(a), rank_of(b)))
        if (ra, rb) != tuple(sorted(ranks)):
            continue
        if kind == "suited" and suit_of(a) != suit_of(b):
            continue
        if kind == "offsuit" and suit_of(a) == suit_of(b):
            continue
        n += 1
    return n


@pytest.mark.parametrize("seed", SEEDS)
def test_combos(seed):
    it = gen_combos(random.Random(seed))
    m = it["math"]
    r1, r2 = ("23456789TJQKA".index(m["ranks"][0]), "23456789TJQKA".index(m["ranks"][1]))
    dead = parse_cards(m["board"])
    mode = m["mode"]
    if mode in ("pair", "blocker_pair"):
        expected = brute_combos((r1, r1), "any", dead)
    elif mode in ("suited", "offsuit"):
        expected = brute_combos((r1, r2), mode, dead)
    else:
        expected = brute_combos((r1, r2), "any", dead)
    fixed = {"pair": 6, "suited": 4, "offsuit": 12, "any": 16, "blocker_pair": 3, "blocker_unpaired": 12}
    assert expected == m["combos"] == fixed[mode]
    assert it["options"][it["answer"]] == str(expected)


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("gen", [gen_draw_allin_flop, gen_draw_turn_bet])
def test_breakdown_generators(seed, gen):
    it = gen(random.Random(seed))
    m = it["math"]
    hero, vil, board = parse_cards(it["hero"]), parse_cards(it["villain"]), parse_cards(it["board"])
    # brute-force equity with the naive evaluator
    deck = remaining_deck(hero + vil + board)
    need = 5 - len(board)
    score = total = 0
    for run in itertools.combinations(deck, need):
        full = board + list(run)
        a, b = naive_best(hero + full), naive_best(vil + full)
        score += 2 if a > b else 1 if a == b else 0
        total += 2
    eq = score / total
    assert abs(eq - m["equity"]) < 1e-12
    assert abs(required_equity(m["pot"], m["bet"]) - m["required"]) < 1e-12
    assert it["play"] == ("CALL" if eq >= m["required"] else "FOLD")
    # villain really has top pair on the dealt board
    vs = evaluate(vil + board)
    assert category(vs) == PAIR and (vs >> 16) & 0xF == max(rank_of(c) for c in board)


@pytest.mark.parametrize("n", range(30))
def test_generated_items_are_valid(n):
    for fmt in ("quiz", "breakdown"):
        it = generate(fmt, n)
        assert validate_item(it) == [], validate_item(it)


def test_generator_is_deterministic():
    assert generate("quiz", 4)["hash"] == generate("quiz", 4)["hash"]
    assert generate("breakdown", 3)["hash"] == generate("breakdown", 3)["hash"]
