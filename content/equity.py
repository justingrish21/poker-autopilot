"""Equity, outs and probability math built on the evaluator in cards.py."""
from __future__ import annotations

import itertools
import random
from math import comb
from typing import Sequence

from .cards import (FLUSH, STRAIGHT, PAIR, category, evaluate, rank_of,
                    remaining_deck)


def monte_carlo_equity(hero: Sequence[int], villain: Sequence[int], board: Sequence[int] = (),
                       iterations: int = 20000, rng: random.Random | None = None) -> float:
    """Hero equity (wins + ties/2) as a fraction, by random runouts."""
    rng = rng or random.Random(0)
    deck = remaining_deck(list(hero) + list(villain) + list(board))
    need = 5 - len(board)
    h, v, b = list(hero), list(villain), list(board)
    ev = evaluate
    sample = rng.sample
    score = 0
    for _ in range(iterations):
        run = b + sample(deck, need)
        a = ev(h + run)
        c = ev(v + run)
        if a > c:
            score += 2
        elif a == c:
            score += 1
    return score / (2 * iterations)


def exact_equity(hero: Sequence[int], villain: Sequence[int], board: Sequence[int]) -> float:
    """Exact hero equity by enumerating every runout (use with a flop or turn board)."""
    deck = remaining_deck(list(hero) + list(villain) + list(board))
    need = 5 - len(board)
    h, v, b = list(hero), list(villain), list(board)
    score = total = 0
    for run in itertools.combinations(deck, need):
        full = b + list(run)
        a = evaluate(h + full)
        c = evaluate(v + full)
        score += 2 if a > c else (1 if a == c else 0)
        total += 2
    return score / total


def improves_to(hero: Sequence[int], board: Sequence[int], card: int, target: int) -> bool:
    """True if adding `card` gives hero a hand of category >= target that beats the board alone."""
    new_board = list(board) + [card]
    s = evaluate(list(hero) + new_board)
    if category(s) < target:
        return False
    if len(new_board) >= 5 and evaluate(new_board) >= s:
        return False  # the board plays; hero didn't improve
    return True


def draw_outs(hero: Sequence[int], board: Sequence[int], extra_dead: Sequence[int] = ()) -> dict:
    """Enumerate the unseen deck and return flush/straight outs (no double counting)."""
    deck = remaining_deck(list(hero) + list(board) + list(extra_dead))
    flush = {c for c in deck if improves_to(hero, board, c, FLUSH)}
    straight_or_better = {c for c in deck if improves_to(hero, board, c, STRAIGHT)}
    straight_only = straight_or_better - flush
    return {
        "flush": sorted(flush),
        "straight": sorted(straight_only),
        "all": sorted(straight_or_better),
        "unseen": len(deck),
    }


def overcard_outs(hero: Sequence[int], board: Sequence[int]) -> list[int]:
    """Cards that pair one of hero's hole cards when both are above the board."""
    deck = remaining_deck(list(hero) + list(board))
    top = max(rank_of(c) for c in board)
    hero_ranks = {rank_of(c) for c in hero}
    outs = []
    for c in deck:
        if rank_of(c) in hero_ranks and rank_of(c) > top:
            s = evaluate(list(hero) + list(board) + [c])
            if category(s) == PAIR:
                outs.append(c)
    return outs


def hit_by_river_exact(outs_count: int, unseen: int) -> float:
    """P(at least one out in the next two cards) from `unseen` cards."""
    return 1 - comb(unseen - outs_count, 2) / comb(unseen, 2)


def hit_next_card_exact(outs_count: int, unseen: int) -> float:
    return outs_count / unseen


def required_equity(pot: float, bet: float) -> float:
    """Break-even equity to call `bet` into `pot` (pot is before villain's bet)."""
    return bet / (pot + 2 * bet)


def round_pct(x: float) -> int:
    """Round a fraction to a whole percent, halves rounding up."""
    return int(x * 100 + 0.5)
