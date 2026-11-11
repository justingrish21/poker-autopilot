"""Procedural, mathematically verified quizzes and breakdowns.

Every generator is deterministic for a given seed and returns a normal content item
plus a `math` dict with the raw numbers (used by the tests to re-check the math).

    generate("quiz", 7)       -> quiz item #7
    generate("breakdown", 3)  -> breakdown item #3
"""
from __future__ import annotations

import itertools
import random
from math import comb

from .cards import (FLUSH, HIGH_CARD, PAIR, RANK_LABEL, RANK_NAME, RANK_PLURAL, RANKS,
                    STRAIGHT, SUIT_NAME, SUITS, card_str, cards_str, category, evaluate,
                    hand_name, parse_card, rank_of, remaining_deck, suit_of)
from .equity import (draw_outs, exact_equity, hit_by_river_exact, hit_next_card_exact,
                     monte_carlo_equity, overcard_outs, required_equity, round_pct)
from .library import normalize

QUIZ_KINDS = ["pot_odds", "outs", "rule_2_4", "preflop_equity", "combos"]
BREAKDOWN_KINDS = ["draw_allin_flop", "draw_turn_bet"]

BET_SIZES = [  # (label, fraction of pot)
    ("1/4 pot", 1 / 4), ("1/3 pot", 1 / 3), ("1/2 pot", 1 / 2), ("2/3 pot", 2 / 3),
    ("3/4 pot", 3 / 4), ("pot", 1.0), ("1.5x pot", 1.5),
]
MC_ITERATIONS = 20000


def generate(fmt: str, n: int) -> dict:
    if fmt == "quiz":
        kind = QUIZ_KINDS[n % len(QUIZ_KINDS)]
        fn = QUIZ_GENERATORS[kind]
    elif fmt == "breakdown":
        kind = BREAKDOWN_KINDS[n % len(BREAKDOWN_KINDS)]
        fn = BREAKDOWN_GENERATORS[kind]
    elif fmt == "allin":
        from .allin import ALLIN_KINDS, gen_allin
        kind = ALLIN_KINDS[n % len(ALLIN_KINDS)]
        fn = lambda r: gen_allin(r, kind)
    else:
        raise ValueError(fmt)
    rng = random.Random(f"{fmt}:{kind}:{n}")
    item = fn(rng)
    item["id"] = f"gen-{fmt}-{n:05d}"
    item["kind"] = kind
    item["generated"] = True
    return normalize(item, fmt)


def generated_id(fmt: str, n: int) -> str:
    return f"gen-{fmt}-{n:05d}"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _shuffle_options(rng: random.Random, correct, wrong: list) -> tuple[list, int]:
    opts = [correct] + list(wrong)
    rng.shuffle(opts)
    return opts, opts.index(correct)


def _sorted_numeric(rng: random.Random, correct: int, wrong: list[int], fmt: str = "{}") -> tuple[list[str], int]:
    """Options in ascending order (reads naturally), answer index tracked."""
    vals = sorted({correct, *wrong})
    assert len(vals) == 1 + len(wrong), "options must be distinct"
    return [fmt.format(v) for v in vals], vals.index(correct)


def _pick_distractors(rng: random.Random, correct: int, candidates: list[int], k: int = 2,
                      min_gap: int = 1, lo: int = 1, hi: int = 99) -> list[int]:
    pool = [c for c in dict.fromkeys(candidates) if c != correct and lo <= c <= hi]
    rng.shuffle(pool)
    chosen: list[int] = []
    for c in pool:
        if all(abs(c - x) >= min_gap for x in chosen + [correct]):
            chosen.append(c)
        if len(chosen) == k:
            break
    if len(chosen) < k:
        raise ValueError("not enough distractors")
    return chosen


def _suit_word(s: int) -> str:
    return SUIT_NAME[SUITS[s]]


def _join_ranks(ranks: list[int]) -> str:
    names = [RANK_NAME[RANKS[r]] for r in sorted(set(ranks), reverse=True)]
    if len(names) == 1:
        return f"Any {names[0]}"
    return "Any " + ", ".join(names[:-1]) + " or " + names[-1]


def is_playable(hand: list[int]) -> bool:
    """Starting hands real players actually take to a flop (keeps spots believable)."""
    hi, lo = sorted((rank_of(hand[0]), rank_of(hand[1])), reverse=True)
    suited = suit_of(hand[0]) == suit_of(hand[1])
    gap = hi - lo
    if hi == 12:  # any ace (A-5 wheel aces gap counts too)
        return suited or lo >= 7
    if suited:
        return lo >= 7 or (gap <= 2 and lo >= 2)
    return lo >= 8 or (gap <= 1 and lo >= 5)


def _has_four_in_row(ranks: set[int]) -> bool:
    rs = set(ranks)
    if 12 in rs:
        rs.add(-1)
    return any(all(r + i in rs for i in range(4)) for r in range(-1, 10))


def deal_draw(rng: random.Random, street: str = "flop", allowed=("flush", "oesd", "gutshot", "combo", "overcards"),
              max_tries: int = 20000) -> dict:
    """Deal hero + board where hero has a clean draw, outs enumerated from the deck."""
    nboard = 3 if street == "flop" else 4
    for _ in range(max_tries):
        cards = rng.sample(range(52), 2 + nboard)
        hero, board = cards[:2], cards[2:]
        if not is_playable(hero):
            continue
        if len({rank_of(c) for c in board}) != nboard:
            continue  # keep boards unpaired: cleaner spots
        if category(evaluate(hero + board)) != HIGH_CARD:
            continue  # hero holds no made hand yet
        o = draw_outs(hero, board)
        nf, ns = len(o["flush"]), len(o["straight"])
        draw = None
        if nf and ns:
            draw = "combo"
        elif nf:
            draw = "flush" if nf == 9 else None
        if draw in ("flush", "combo") and suit_of(hero[0]) != suit_of(hero[1]):
            draw = None  # only count flush draws that use both hole cards
        elif ns == 8:
            hb = {rank_of(c) for c in hero + board}
            draw = "oesd" if _has_four_in_row(hb) else None  # skip double-gutters
        elif ns == 4:
            draw = "gutshot"
        elif ns == 0:
            top = max(rank_of(c) for c in board)
            if min(rank_of(c) for c in hero) > top and rank_of(hero[0]) != rank_of(hero[1]):
                draw = "overcards"
        if draw is None or draw not in allowed:
            continue
        if draw == "overcards":
            outs = overcard_outs(hero, board)
            if len(outs) != 6:
                continue
        else:
            outs = o["all"]
        return {"hero": hero, "board": board, "draw": draw, "outs": outs,
                "flush_outs": o["flush"], "straight_outs": o["straight"], "unseen": o["unseen"]}
    raise RuntimeError("could not deal a draw")


DRAW_NAME = {
    "flush": "flush draw", "oesd": "open-ended straight draw", "gutshot": "gutshot straight draw",
    "combo": "straight + flush draw", "overcards": "two overcards",
}
DRAW_TARGET = {
    "flush": "a flush", "oesd": "a straight", "gutshot": "a straight",
    "combo": "a straight or flush", "overcards": "top pair",
}


def outs_explanation(d: dict) -> str:
    n = len(d["outs"])
    if d["draw"] == "flush":
        s = _suit_word(suit_of(d["flush_outs"][0]))
        return f"13 {s} total, 4 are showing, so {n} are left. {n} outs."
    if d["draw"] in ("oesd", "gutshot"):
        ranks = [rank_of(c) for c in d["outs"]]
        per = n // len(set(ranks))
        parts = " + ".join([str(per)] * len(set(ranks)))
        if len(set(ranks)) == 1:
            return f"{_join_ranks(ranks)} makes your straight. 4 left in the deck = {n} outs."
        return f"{_join_ranks(ranks)} makes your straight: {parts} = {n} outs."
    if d["draw"] == "combo":
        s = _suit_word(suit_of(d["flush_outs"][0]))
        nf, ns = len(d["flush_outs"]), len(d["straight_outs"])
        return (f"{nf} {s} + {ns} more straight cards = {n} outs. "
                f"Straight cards that are {s} only count once.")
    ranks = sorted({rank_of(c) for c in d["outs"]}, reverse=True)
    names = " or ".join(RANK_NAME[RANKS[r]] for r in ranks)
    return f"3 cards left of each overcard. Any {names}: 3 + 3 = {n} outs."


# ---------------------------------------------------------------------------
# Quizzes
# ---------------------------------------------------------------------------

def gen_pot_odds(rng: random.Random) -> dict:
    label, frac = rng.choice(BET_SIZES)
    pot = 12 * rng.randint(1, 20)  # multiples of 12 keep every bet size a whole number
    bet = round(pot * frac)
    req = required_equity(pot, bet)
    correct = round_pct(req)
    naive = round_pct(bet / (pot + bet))  # classic mistake: forgetting your own call
    cands = [naive, correct + 8, correct - 7, correct + 12, correct - 10, round_pct(bet / pot)]
    wrong = _pick_distractors(rng, correct, cands, k=2, min_gap=5, lo=3, hi=90)
    options, answer = _sorted_numeric(rng, correct, wrong, "{}%")
    total = pot + 2 * bet
    return {
        "hook": rng.choice([f"Villain bets {label}. Do you have the odds?", "Pot odds in 5 seconds. Go.",
                            "Call or fold? Do the math first.", "Can you get this right?"]),
        "q": f"Pot is {pot}bb. Villain bets {bet}bb ({label}). What equity do you need to call?",
        "setup": "Pot odds quiz",
        "hero": [], "board": [],
        "options": options, "answer": answer,
        "explain": f"You call {bet} to win {total} total ({pot} + {bet} + {bet}). {bet} / {total} = {correct}%.",
        "caption": f"Villain bets {label}. How much equity do you need to call? Comment your answer.",
        "math": {"pot": pot, "bet": bet, "required": req, "correct_pct": correct},
    }


def gen_outs(rng: random.Random) -> dict:
    d = deal_draw(rng, "flop")
    n = len(d["outs"])
    cands = [4, 6, 8, 9, 12, 13, 15, n - 1, n + 1, n + 2, n - 2, n + 3]
    wrong = _pick_distractors(rng, n, cands, k=2, min_gap=1, lo=2, hi=20)
    options, answer = _sorted_numeric(rng, n, wrong)
    return {
        "hook": rng.choice(["You're on a draw. Count your outs. Go.", "Bet you miscount this one",
                            "How many outs? Be honest.", "Can you get this right?"]),
        "q": f"You have a {DRAW_NAME[d['draw']]}. How many outs to make {DRAW_TARGET[d['draw']]}?",
        "setup": "Outs quiz  |  Flop",
        "hero": cards_str(d["hero"]), "board": cards_str(d["board"]),
        "options": options, "answer": answer,
        "explain": outs_explanation(d),
        "caption": f"{DRAW_NAME[d['draw']].capitalize()}: how many outs? Comment before the reveal.",
        "math": {"draw": d["draw"], "outs": cards_str(d["outs"]), "n_outs": n},
    }


def gen_rule_2_4(rng: random.Random) -> dict:
    street = rng.choice(["flop", "flop", "turn"])
    d = deal_draw(rng, street, allowed=("flush", "oesd", "gutshot", "combo"))
    n, unseen = len(d["outs"]), d["unseen"]
    if street == "flop":
        estimate, exact = 4 * n, hit_by_river_exact(n, unseen)
        wrong = [2 * n, 6 * n] if 6 * n <= 95 else [n, 2 * n]
        rule = f"Rule of 4: {n} outs x 4 = {estimate}%"
        q = f"{n} outs on the flop. Rule of 4: chance to hit by the river?"
        exact_txt = f"Exact from the deck: {exact * 100:.1f}%."
    else:
        estimate, exact = 2 * n, hit_next_card_exact(n, unseen)
        wrong = [n, 4 * n]
        rule = f"Rule of 2: {n} outs x 2 = {estimate}%"
        q = f"{n} outs on the turn. Rule of 2: chance to hit on the river?"
        exact_txt = f"Exact: {n} / {unseen} = {exact * 100:.1f}%."
    options, answer = _sorted_numeric(rng, estimate, wrong, "{}%")
    return {
        "hook": rng.choice(["Do this in your head in 3 seconds", "The poker math trick pros use",
                            "Your odds to hit? Quick math.", "Can you get this right?"]),
        "q": q,
        "setup": f"Rule of 2 and 4  |  {DRAW_NAME[d['draw']].capitalize()}",
        "hero": cards_str(d["hero"]), "board": cards_str(d["board"]),
        "options": options, "answer": answer,
        "explain": f"{rule}. {exact_txt}",
        "caption": "Outs x 4 on the flop, x 2 on the turn. Did you get it right?",
        "math": {"street": street, "n_outs": n, "unseen": unseen, "estimate": estimate, "exact": exact,
                 "outs": cards_str(d["outs"])},
    }


BUCKET_EDGES = [0, 15, 30, 45, 60, 75, 90, 100]


def _bucket_label(i: int) -> str:
    return f"{BUCKET_EDGES[i]}-{BUCKET_EDGES[i + 1]}%"


def gen_preflop_equity(rng: random.Random) -> dict:
    for _ in range(200):
        cards = rng.sample(range(52), 4)
        hero, villain = cards[:2], cards[2:]
        if not (is_playable(hero) and is_playable(villain)):
            continue
        eq = monte_carlo_equity(hero, villain, (), MC_ITERATIONS, random.Random(rng.random()))
        pct = eq * 100
        if min(abs(pct - e) for e in BUCKET_EDGES[1:-1]) < 1.5:
            continue  # too close to a bucket edge to be sure with Monte Carlo noise
        b = next(i for i in range(len(BUCKET_EDGES) - 1) if pct < BUCKET_EDGES[i + 1] or i == len(BUCKET_EDGES) - 2)
        nb = len(BUCKET_EDGES) - 1
        start = min(max(b - rng.randint(0, 2), 0), nb - 3)
        options = [_bucket_label(i) for i in range(start, start + 3)]
        answer = b - start
        hs, vs = cards_str(hero), cards_str(villain)
        hn, vn = hand_name(*hs), hand_name(*vs)
        return {
            "hook": rng.choice([f"{hn} vs {vn}. Who wins?", "All in preflop. Guess the equity.",
                                "This matchup surprises people", "Who's really ahead?"]),
            "q": f"{hn[0].upper() + hn[1:]} vs {vn}, all in preflop. What's your equity?",
            "setup": "Equity quiz  |  All in preflop",
            "hero": hs, "villain": vs, "board": [],
            "options": options, "answer": answer,
            "explain": f"Over {MC_ITERATIONS:,} simulated runouts, {hn} has {pct:.1f}% equity vs {vn}.",
            "caption": f"{hn} vs {vn} all in. How often do you win? Comment your guess.",
            "math": {"hero": hs, "villain": vs, "equity": eq, "bucket": options[answer]},
        }
    raise RuntimeError("no equity spot found")


def count_combos(rank_a: int, rank_b: int, kind: str, dead: list[int]) -> int:
    """Brute-force count of 2-card combos from the live deck. kind: pair/suited/offsuit/any."""
    deck = remaining_deck(dead)
    n = 0
    for x, y in itertools.combinations(deck, 2):
        rx, ry = rank_of(x), rank_of(y)
        if {rx, ry} != {rank_a, rank_b} or (rank_a == rank_b) != (rx == ry):
            continue
        if kind == "suited" and suit_of(x) != suit_of(y):
            continue
        if kind == "offsuit" and suit_of(x) == suit_of(y):
            continue
        n += 1
    return n


def gen_combos(rng: random.Random) -> dict:
    mode = rng.choice(["pair", "suited", "offsuit", "any", "blocker_pair", "blocker_unpaired"])
    r1, r2 = sorted(rng.sample(range(13), 2), reverse=True)
    ra, rb = RANKS[r1], RANKS[r2]
    a, b = RANK_LABEL[ra], RANK_LABEL[rb]
    sep = "-" if "10" in (a, b) else ""
    hand = f"{a}{sep}{b}"
    s1, s2 = rng.sample(SUITS, 2)
    board: list[str] = []
    hero: list[str] = []
    if mode == "pair":
        n = count_combos(r1, r1, "pair", [])
        q = f"How many ways can you be dealt pocket {RANK_PLURAL[ra]}?"
        explain = f"4 {RANK_PLURAL[ra].lower()} in the deck. 4 x 3 / 2 = {n} combos."
        hero = [ra + s1, ra + s2]
        wrong = _pick_distractors(rng, n, [4, 8, 12, 16, 3], min_gap=1)
    elif mode == "suited":
        n = count_combos(r1, r2, "suited", [])
        q = f"How many combos of {hand} suited exist?"
        explain = f"One for each suit: {n} suited combos."
        hero = [ra + s1, rb + s1]
        wrong = _pick_distractors(rng, n, [6, 8, 12, 16, 2], min_gap=1)
    elif mode == "offsuit":
        n = count_combos(r1, r2, "offsuit", [])
        q = f"How many combos of {hand} offsuit exist?"
        explain = f"4 x 4 = 16 total, minus 4 suited = {n} offsuit combos."
        hero = [ra + s1, rb + s2]
        wrong = _pick_distractors(rng, n, [4, 6, 8, 16, 9], min_gap=1)
    elif mode == "any":
        n = count_combos(r1, r2, "any", [])
        q = f"How many total combos of {hand} exist?"
        explain = f"4 {RANK_PLURAL[ra].lower()} x 4 {RANK_PLURAL[rb].lower()} = {n} combos (4 suited + 12 offsuit)."
        hero = [ra + s1, rb + s2]
        wrong = _pick_distractors(rng, n, [4, 6, 8, 12, 24], min_gap=1)
    elif mode == "blocker_pair":
        board_card = ra + s1
        others = [c for c in RANKS if c != ra]
        filler = rng.sample(others, 2)
        board = [board_card] + [f + rng.choice(SUITS) for f in filler]
        dead = [parse_card(c) for c in board]
        n = count_combos(r1, r1, "pair", dead)
        q = f"One {RANK_NAME[ra].lower()} is on the board. How many combos of pocket {RANK_PLURAL[ra]} are left?"
        explain = f"Only 3 {RANK_PLURAL[ra].lower()} left. 3 x 2 / 2 = {n} combos (down from 6)."
        wrong = _pick_distractors(rng, n, [1, 2, 4, 6], min_gap=1)
    else:  # blocker_unpaired
        others = [c for c in RANKS if c not in (ra, rb)]
        filler = rng.sample(others, 2)
        board = [ra + s1, filler[0] + rng.choice(SUITS), filler[1] + rng.choice(SUITS)]
        dead = [parse_card(c) for c in board]
        n = count_combos(r1, r2, "any", dead)
        q = f"One {RANK_NAME[ra].lower()} is on the board. How many {hand} combos are left?"
        explain = f"3 {RANK_PLURAL[ra].lower()} left x 4 {RANK_PLURAL[rb].lower()} = {n} combos (down from 16)."
        wrong = _pick_distractors(rng, n, [9, 16, 8, 6, 4], min_gap=1)
    options, answer = _sorted_numeric(rng, n, wrong)
    return {
        "hook": rng.choice(["The skill that separates regs from fish", "Regs know this one. Do you?",
                            "Combo counting: pro skill unlocked", "Can you get this right?"]),
        "q": q,
        "setup": "Combos quiz",
        "hero": hero, "board": board,
        "options": options, "answer": answer,
        "explain": explain,
        "caption": "Combo counting is how good players read ranges. Did you get it?",
        "math": {"mode": mode, "ranks": [ra, rb], "board": board, "combos": n},
    }


# ---------------------------------------------------------------------------
# Breakdowns
# ---------------------------------------------------------------------------

def _villain_top_pair(rng: random.Random, hero: list[int], board: list[int], outs: list[int]) -> list[int] | None:
    """A villain hand with exactly top pair that doesn't block hero's outs."""
    top = max(rank_of(c) for c in board)
    used = set(hero) | set(board)
    blocked = set(outs)
    tops = [c for c in range(52) if rank_of(c) == top and c not in used and c not in blocked]
    rng.shuffle(tops)
    for t in tops:
        kicks = [c for c in range(52) if c not in used and c != t and c not in blocked]
        rng.shuffle(kicks)
        for k in kicks[:30]:
            v = [t, k]
            s = evaluate(v + board)
            if category(s) == PAIR and (s >> 16) & 0xF == top:
                return v
    return None


def _decision_lines(eq: float, req: float, implied_ok: bool) -> tuple[str, str]:
    eqp, reqp = round_pct(eq), round_pct(req)
    play = "CALL" if eq >= req else "FOLD"
    diff = (eq - req) * 100
    if abs(diff) <= 5:
        if implied_ok and play == "FOLD":
            note = "Close spot: deep stacks + implied odds can turn this into a call"
        elif implied_ok:
            note = "Close, but the math says call (implied odds are a bonus)"
        else:
            note = "It's all in, so no implied odds: the math decides"
    elif play == "CALL":
        note = f"Your equity beats the price by {eqp - reqp} points: easy call"
    else:
        note = f"You're {reqp - eqp} points short. Chasing here loses chips long term"
    return play, note


def gen_draw_allin_flop(rng: random.Random) -> dict:
    for _ in range(200):
        d = deal_draw(rng, "flop", allowed=("flush", "oesd", "combo", "gutshot"))
        v = _villain_top_pair(rng, d["hero"], d["board"], d["outs"])
        if v:
            break
    else:
        raise RuntimeError("no villain hand")
    pot = 4 * rng.randint(3, 15)
    label, frac = rng.choice([b for b in BET_SIZES if b[1] >= 0.5])
    shove = round(pot * frac)
    req = required_equity(pot, shove)
    eq = exact_equity(d["hero"], v, d["board"])
    play, note = _decision_lines(eq, req, implied_ok=False)
    name = DRAW_NAME[d["draw"]]
    hook = rng.choice(["He shoves. You're on a draw. Call?", f"All in on the flop. Call with a {name}?",
                       "He jams. Do you have the odds?", "Hero call or hero fold?"])
    return {
        "hook": hook,
        "setup": f"Flop  |  Pot {pot}bb  |  Villain shoves {shove}bb ({label})",
        "hero": cards_str(d["hero"]), "board": cards_str(d["board"]), "villain": cards_str(v),
        "action": f"Villain has top pair. You have a {name} ({len(d['outs'])} outs).",
        "play": play,
        "why": [
            f"Price: {shove} / ({pot} + {shove} + {shove}) = you need {round_pct(req)}%",
            f"Your real equity vs his hand: {round_pct(eq)}% (every runout counted)",
            note,
        ],
        "caption": f"{name.capitalize()} vs an all in. Call or fold? The math decides.",
        "math": {"pot": pot, "bet": shove, "required": req, "equity": eq, "street": "flop",
                 "n_outs": len(d["outs"])},
    }


def gen_draw_turn_bet(rng: random.Random) -> dict:
    for _ in range(200):
        d = deal_draw(rng, "turn", allowed=("flush", "oesd", "combo", "gutshot"))
        v = _villain_top_pair(rng, d["hero"], d["board"], d["outs"])
        if v:
            break
    else:
        raise RuntimeError("no villain hand")
    pot = 4 * rng.randint(4, 20)
    label, frac = rng.choice(BET_SIZES)
    bet = round(pot * frac)
    req = required_equity(pot, bet)
    eq = exact_equity(d["hero"], v, d["board"])
    play, note = _decision_lines(eq, req, implied_ok=True)
    name = DRAW_NAME[d["draw"]]
    hook = rng.choice(["One card to go. Do you chase?", f"Turn {name}: call or fold?",
                       "Stop chasing draws without this math", "Chase it or let it go?"])
    return {
        "hook": hook,
        "setup": f"Turn  |  Pot {pot}bb  |  Villain bets {bet}bb ({label})",
        "hero": cards_str(d["hero"]), "board": cards_str(d["board"]), "villain": cards_str(v),
        "action": f"Villain has top pair. One card to come. You have {len(d['outs'])} outs.",
        "play": play,
        "why": [
            f"Price: {bet} / ({pot} + {bet} + {bet}) = you need {round_pct(req)}%",
            f"Your equity on the river: {round_pct(eq)}% vs his exact hand",
            note,
        ],
        "caption": f"Turn {name} facing a {label} bet. Call or fold? Here's the math.",
        "math": {"pot": pot, "bet": bet, "required": req, "equity": eq, "street": "turn",
                 "n_outs": len(d["outs"])},
    }


QUIZ_GENERATORS = {
    "pot_odds": gen_pot_odds, "outs": gen_outs, "rule_2_4": gen_rule_2_4,
    "preflop_equity": gen_preflop_equity, "combos": gen_combos,
}
BREAKDOWN_GENERATORS = {"draw_allin_flop": gen_draw_allin_flop, "draw_turn_bet": gen_draw_turn_bet}
