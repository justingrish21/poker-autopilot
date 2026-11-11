"""All-in stories, styled like a hand played in a mobile poker client.

Kinds:
  badbeat  PokerPilot gets it in as a big favorite and loses on the river.
  suckout  PokerPilot gets it in as an underdog and hits a miracle river.
  cooler   Big hand vs big hand (set over set, set over two pair, straight over set):
           PokerPilot holds and ships it.

All numbers are computed: preflop equity by 20,000-runout Monte Carlo, flop/turn equity
by enumerating every runout, river outs by enumerating the deck.
"""
from __future__ import annotations

import random

from .cards import (PAIR, RANKS, RANK_NAME, SUIT_NAME, SUITS, TWO_PAIR, cards_str, category,
                    describe_hand, evaluate, hand_name, rank_of, remaining_deck, suit_of)
from .equity import exact_equity, monte_carlo_equity, round_pct

ALLIN_KINDS = ["badbeat", "suckout", "cooler"]
HERO_NAME = "PokerPilot"
NUM_SEATS = 5          # 0,1 = top, 2,3 = middle, 4 = PokerPilot (bottom)
VILLAIN_SEATS = (2, 3)

_FIRST = ["River", "Lucky", "Ace", "Nit", "Chip", "Bluff", "Tilt", "Nuts", "Card", "Pocket", "Monk",
          "Ghost", "Jinx", "Turbo", "Cooler", "Sly", "Maverick", "Royal", "Gutshot", "Grinder", "Flop",
          "Felt", "Stack", "Wild", "Silent", "Golden", "Midnight", "Iron", "Neon", "Shadow"]
_SECOND = ["King", "Queen", "Hunter", "Master", "Wizard", "Lord", "Boss", "Kid", "Fox", "Bandit",
           "Rider", "Ninja", "Baron", "Wolf", "Shark", "Rat", "Viper", "Ace", "Joker", "Duke", "Owl",
           "Tiger", "Falcon", "Cowboy", "Panda"]
AVATAR_COLORS = [(231, 76, 60), (52, 152, 219), (155, 89, 182), (241, 196, 15), (26, 188, 156),
                 (230, 126, 34), (236, 112, 160), (149, 165, 166), (46, 204, 113), (93, 109, 255)]


def random_name(rng: random.Random, taken: set[str]) -> str:
    for _ in range(100):
        a, b = rng.choice(_FIRST), rng.choice(_SECOND)
        style = rng.random()
        if style < 0.35:
            n = f"{a}{b}"
        elif style < 0.6:
            n = f"{a}{b}{rng.randint(2, 99)}"
        elif style < 0.8:
            n = f"{a.lower()}_{b.lower()}"
        else:
            n = f"{a}{rng.randint(1, 9)}{b[0]}"
        if n not in taken and n.lower() != HERO_NAME.lower() and len(n) <= 13:
            return n
    return f"Player{rng.randint(100, 999)}"


# ---------------------------------------------------------------------------
# dealing
# ---------------------------------------------------------------------------

def _premium(rng: random.Random, deck: list[int]) -> list[int]:
    r = rng.choice(["A", "A", "A", "K", "K", "Q", "AK"])
    if r == "AK":
        return [rng.choice([c for c in deck if RANKS[rank_of(c)] == "A"]),
                rng.choice([c for c in deck if RANKS[rank_of(c)] == "K"])]
    return rng.sample([c for c in deck if RANKS[rank_of(c)] == r], 2)


def _playable(hand: list[int]) -> bool:
    hi, lo = sorted((rank_of(hand[0]), rank_of(hand[1])), reverse=True)
    suited = suit_of(hand[0]) == suit_of(hand[1])
    if hi == lo or hi == 12:
        return True
    if suited:
        return lo >= 5 or hi - lo <= 2
    return lo >= 7 or (hi - lo <= 1 and lo >= 4)


def _ahead(a, b, board) -> bool:
    return evaluate(a + board) > evaluate(b + board)


def _unpaired(cards) -> bool:
    return len({rank_of(c) for c in cards}) == len(cards)


def deal_runout(rng: random.Random, street: str, max_tries: int = 300000) -> dict:
    """Favorite is ahead on flop and turn (>= 75% on the turn); the underdog wins on the river."""
    for _ in range(max_tries):
        deck = list(range(52))
        fav = _premium(rng, deck) if street == "preflop" else rng.sample(deck, 2)
        if street != "preflop" and not _playable(fav):
            continue
        rest = [c for c in deck if c not in fav]
        dog = rng.sample(rest, 2)
        if not _playable(dog):
            continue
        rest = [c for c in rest if c not in dog]
        board = rng.sample(rest, 5)
        if evaluate(dog + board) <= evaluate(fav + board):
            continue
        if not (_ahead(fav, dog, board[:3]) and _ahead(fav, dog, board[:4])):
            continue
        if street != "preflop" and not _unpaired(board[:4 if street == "turn" else 3]):
            continue
        eq_turn = exact_equity(fav, dog, board[:4])
        if eq_turn < 0.75:
            continue
        if street == "flop" and category(evaluate(fav + board[:3])) < TWO_PAIR:
            continue
        if street == "turn" and (eq_turn < 0.8 or category(evaluate(fav + board[:4])) < TWO_PAIR):
            continue
        if street == "preflop" and category(evaluate(dog + board[:3])) >= TWO_PAIR:
            continue
        eq_flop = exact_equity(fav, dog, board[:3])
        if street == "flop" and eq_flop < 0.7:
            continue
        eq_pre = None
        if street == "preflop":
            eq_pre = monte_carlo_equity(fav, dog, (), 20000, random.Random(rng.random()))
            if eq_pre < 0.7:
                continue
        return {"fav": fav, "dog": dog, "board": board, "eq_pre": eq_pre, "eq_flop": eq_flop, "eq_turn": eq_turn}
    raise RuntimeError("no runout found")


def deal_cooler(rng: random.Random, max_tries: int = 20000) -> dict:
    """Two monsters on an unpaired flop; the bigger one (hero) holds through the river."""
    for _ in range(max_tries):
        flop = rng.sample(range(52), 3)
        if not _unpaired(flop):
            continue
        ranks = sorted({rank_of(c) for c in flop}, reverse=True)
        deck = [c for c in range(52) if c not in flop]
        style = rng.choice(["set_over_set", "set_over_two_pair", "set_over_two_pair", "straight_over_set"])
        try:
            if style == "set_over_set":
                hr, vr = ranks[0], rng.choice(ranks[1:])
                hero = rng.sample([c for c in deck if rank_of(c) == hr], 2)
                villain = rng.sample([c for c in deck if rank_of(c) == vr], 2)
            elif style == "set_over_two_pair":
                hr = rng.choice(ranks)
                others = [r for r in ranks if r != hr]
                hero = rng.sample([c for c in deck if rank_of(c) == hr], 2)
                villain = [rng.choice([c for c in deck if rank_of(c) == r]) for r in others]
            else:
                hero = rng.sample(deck, 2)
                vr = rng.choice(ranks)
                villain = rng.sample([c for c in deck if rank_of(c) == vr and c not in hero], 2)
        except (ValueError, IndexError):
            continue
        if len(set(hero + villain + flop)) != 7:
            continue
        hs, vs = evaluate(hero + flop), evaluate(villain + flop)
        if hs <= vs or category(vs) < TWO_PAIR:
            continue
        if style == "straight_over_set" and category(hs) != 4:
            continue
        rest = [c for c in range(52) if c not in hero + villain + flop]
        tr = rng.sample(rest, 2)
        board = flop + tr
        if not (_ahead(hero, villain, board[:4]) and _ahead(hero, villain, board)):
            continue
        eq_flop = exact_equity(hero, villain, flop)
        eq_turn = exact_equity(hero, villain, board[:4])
        if eq_flop < 0.6:
            continue
        return {"hero": hero, "villain": villain, "board": board, "eq_pre": None, "eq_flop": eq_flop,
                "eq_turn": eq_turn, "style": style}
    raise RuntimeError("no cooler found")


# ---------------------------------------------------------------------------
# story text
# ---------------------------------------------------------------------------

def _card_phrase(outs: list[int], wanted: bool) -> str:
    suits = {suit_of(c) for c in outs}
    ranks = sorted({rank_of(c) for c in outs}, reverse=True)
    names = [RANK_NAME[RANKS[r]] for r in ranks]
    art = lambda n: "an" if n[0] in "AE" else "a"
    if len(outs) >= 5 and len(suits) == 1:
        s = SUIT_NAME[SUITS[next(iter(suits))]][:-1]
        return f"One {s}. That's all I need..." if wanted else f"Anything but a {s}..."
    if len(ranks) == 1:
        return (f"Give me {art(names[0])} {names[0]}..." if wanted else f"Anything but {art(names[0])} {names[0]}...")
    if len(ranks) == 2:
        return (f"{names[0]} or {names[1]}. Come on..." if wanted else f"No {names[0]} or {names[1]} please...")
    return f"{len(outs)} outs. Come on..." if wanted else f"Just dodge {len(outs)} cards..."


def _made(score: int) -> str:
    d = describe_hand(score).split(",")[0].lower()
    return {"three of a kind": "a set", "two pair": "two pair", "straight": "a straight", "flush": "a flush",
            "full house": "a full house", "four of a kind": "quads"}.get(d, d)


def _streets(street: str, villain_seat: int, eff: int, hero_shoves: bool, rng: random.Random) -> list[dict]:
    """Betting script. Amounts are each player's total bet for that street (capped by stack)."""
    folders = [s for s in range(4) if s != villain_seat]
    rng.shuffle(folders)
    v, h = villain_seat, 4
    if street == "preflop":
        return [{"street": "preflop", "actions": [
            [folders[0], "fold", 0], [v, "raise", rng.choice([250, 300])], [folders[1], "fold", 0],
            [folders[2], "fold", 0], [h, "raise", rng.choice([900, 1000, 1100])], [v, "allin", eff * 3],
            [h, "call", eff * 3]]}]
    open_ = rng.choice([250, 300])
    pre = {"street": "preflop", "actions": [
        [folders[0], "fold", 0], [v, "raise", open_], [folders[1], "fold", 0], [folders[2], "fold", 0],
        [h, "call", open_]]}
    if street == "flop":
        bet = rng.choice([300, 350, 400])
        if hero_shoves:  # villain bets, PokerPilot shoves, villain calls
            acts = [[v, "bet", bet], [h, "allin", eff * 3], [v, "call", eff * 3]]
        else:            # villain bets, PokerPilot raises, villain shoves, PokerPilot calls
            acts = [[v, "bet", bet], [h, "raise", bet * 3], [v, "allin", eff * 3], [h, "call", eff * 3]]
        return [pre, {"street": "flop", "actions": acts}]
    bet = rng.choice([350, 400])
    return [pre,
            {"street": "flop", "actions": [[v, "bet", bet], [h, "call", bet]]},
            {"street": "turn", "actions": [[v, "check", 0], [h, "allin", eff * 3], [v, "call", eff * 3]]}]


def gen_allin(rng: random.Random, kind: str) -> dict:
    if kind == "cooler":
        street = "flop"
        d = deal_cooler(rng)
        hero, villain, board = d["hero"], d["villain"], d["board"]
        eq = {"preflop": None, "flop": d["eq_flop"], "turn": d["eq_turn"]}
    else:
        street = rng.choice(["preflop", "preflop", "flop", "turn"])
        d = deal_runout(rng, street)
        if kind == "badbeat":
            hero, villain = d["fav"], d["dog"]
            eq = {"preflop": d["eq_pre"], "flop": d["eq_flop"], "turn": d["eq_turn"]}
        else:  # suckout: PokerPilot is the underdog
            hero, villain = d["dog"], d["fav"]
            eq = {"preflop": None if d["eq_pre"] is None else 1 - d["eq_pre"],
                  "flop": 1 - d["eq_flop"], "turn": 1 - d["eq_turn"]}
        board = d["board"]
    hero_wins = kind != "badbeat"
    villain_seat = rng.choice(VILLAIN_SEATS)
    eff = 100 * rng.randint(60, 140)
    taken: set[str] = set()
    seats = []
    colors = rng.sample(AVATAR_COLORS, NUM_SEATS)
    for s in range(NUM_SEATS):
        if s == 4:
            name = HERO_NAME
            stack = eff + (100 * rng.randint(30, 90) if hero_wins else 0)
        else:
            name = random_name(rng, taken)
            stack = (eff + (0 if hero_wins else 100 * rng.randint(30, 90))) if s == villain_seat \
                else 100 * rng.randint(40, 250)
        taken.add(name)
        seats.append({"name": name, "stack": stack, "color": list(colors[s])})
    streets = _streets(street, villain_seat, eff, hero_shoves=(kind != "cooler" or rng.random() < 0.5), rng=rng)

    deck44 = remaining_deck(hero + villain + board[:4])
    # cards on the river that make the eventual winner win
    if hero_wins:
        outs = [c for c in deck44 if evaluate(hero + board[:4] + [c]) > evaluate(villain + board[:4] + [c])]
    else:
        outs = [c for c in deck44 if evaluate(villain + board[:4] + [c]) > evaluate(hero + board[:4] + [c])]
    n_outs = len(outs)
    p_out = n_outs / 44
    hs, vs = cards_str(hero), cards_str(villain)
    hn, vn = hand_name(*hs), hand_name(*vs)
    Hn = hn[0].upper() + hn[1:]
    eq_allin = eq[street]
    pct = round_pct(eq_allin)
    final_hero = describe_hand(evaluate(hero + board))
    final_vil = describe_hand(evaluate(villain + board))
    hero_made = _made(evaluate(hero + board[:3]))
    vil_made = _made(evaluate(villain + board[:3]))

    if kind == "badbeat":
        hooks = {"preflop": [f"{Hn} all in preflop. What could go wrong?", "I had him CRUSHED...",
                             f"{pct}% favorite. Watch this.", "This is why poker is cruel"],
                 "flop": [f"I flopped {hero_made}. He had no idea...", f"{pct}% on the flop. Easy, right?",
                          "The river had other plans", "Worst beat of the week"],
                 "turn": [f"{pct}% with one card to go...", f"I had {_made(evaluate(hero + board[:4]))} on the turn. Then this.",
                          "Never trust the river", "This is why poker is cruel"]}[street]
        caps = {"showdown": f"He has {vn}. I'm {pct}% to win.",
                "flop": f"Clean flop. {round_pct(eq['flop'])}% now.",
                "turn": f"{round_pct(eq['turn'])}%. One card to go...",
                "sweat": _card_phrase(outs, wanted=False), "river": "NO WAY.",
                "after": f"He had {n_outs} out{'s' if n_outs != 1 else ''}. {p_out * 100:.1f}% and he hit it."}
        tiktok = f"{pct}% favorite and still lost to {final_vil.split(',')[0].lower()}. Would you have called?"
    elif kind == "suckout":
        hooks = {"preflop": [f"{Hn} vs his {vn}. I'm in BIG trouble...", "I needed a miracle...",
                             f"Only {pct}% to win. Watch the river.", "Never give up on a hand"],
                 "flop": [f"Only {pct}% on the flop. Then this.", "I was basically dead...",
                          "Never give up on a hand", "The river owed me one"],
                 "turn": [f"{pct}% with one card to go...", "I needed a miracle on the river...",
                          "Down to my last outs", "The river owed me one"]}[street]
        caps = {"showdown": f"He has {vn}. I'm only {pct}% to win.",
                "flop": f"Still behind. {round_pct(eq['flop'])}%.",
                "turn": f"{round_pct(eq['turn'])}%. I need a miracle...",
                "sweat": _card_phrase(outs, wanted=True), "river": "LET'S GO!",
                "after": f"{n_outs} out{'s' if n_outs != 1 else ''}. {p_out * 100:.1f}% and I hit it."}
        tiktok = f"Only {round_pct(eq['turn'])}% on the turn and hit {final_hero.split(',')[0].lower()} on the river. Lucky or good?"
    else:
        # the sweat is about HIS outs: river cards that would have saved him
        his = [c for c in deck44 if evaluate(villain + board[:4] + [c]) > evaluate(hero + board[:4] + [c])]
        bare = lambda x: x[2:] if x.startswith("a ") else x
        if hero_made == vil_made == "a set":
            matchup, after = "Set over set", "Set over set. Brutal for him."
        else:
            matchup = f"{bare(hero_made).capitalize()} vs {bare(vil_made)}"
            after = f"His {bare(vil_made)} into my {bare(hero_made)}. Brutal for him."
        hooks = [f"I flopped {hero_made}. He flopped {vil_made}.", "The most expensive flop of his life",
                 f"{matchup}. Who's paying who?", "When both players flop BIG"]
        caps = {"showdown": f"He has {vil_made}. I'm {pct}% to win.",
                "flop": "", "turn": f"{round_pct(eq['turn'])}%. Just hold...",
                "sweat": _card_phrase(his, wanted=False) if his else "He's drawing dead...",
                "river": "SHIP IT!", "after": after}
        n_outs, p_out = len(his), len(his) / 44
        tiktok = f"{matchup} on the flop. Could you ever fold his hand?"
    hook = rng.choice(hooks)
    return {
        "hook": hook,
        "setup": "No-Limit Hold'em  |  Blinds 50/100  |  Play chips",
        "hero": hs, "villain": vs, "board": cards_str(board),
        "seats": seats, "villain_seat": villain_seat, "streets": streets, "allin_street": street,
        "outcome": "hero" if hero_wins else "villain",
        "equity": eq, "outs": cards_str(outs), "captions": caps, "caption": tiktok,
        "math": {"eq_allin": eq_allin, "eq": eq, "n_outs": n_outs, "p_out": p_out,
                 "hero_final": final_hero, "villain_final": final_vil},
    }
