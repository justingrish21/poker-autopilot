"""Library validity, rotation rules, captions and compliance."""
from __future__ import annotations

import json
import re

import pytest

from content.cards import RANKS, SUITS
from content.library import LIBRARY_PATH, compliance_problems, load_library, validate_item
from content.rotation import next_format, next_item
from publish.captions import CLUB_LINE, HASHTAGS, build_caption

LIB = load_library()
ALL = LIB["breakdown"] + LIB["quiz"]


def test_library_counts():
    assert len(LIB["breakdown"]) == 14 and len(LIB["quiz"]) == 14


@pytest.mark.parametrize("item", ALL, ids=[i["id"] for i in ALL])
def test_library_item_valid(item):
    cards = item["hero"] + item["board"] + item.get("villain", [])
    for c in cards:
        assert len(c) == 2 and c[0] in RANKS and c[1] in SUITS, c
    assert len(cards) == len(set(cards)), f"duplicate card in {item['id']}"
    assert validate_item(item) == []


def test_library_ids_and_hashes_unique():
    assert len({i["id"] for i in ALL}) == len(ALL)
    assert len({i["hash"] for i in ALL}) == len(ALL)


def test_library_json_is_raw_as_given():
    raw = json.loads(LIBRARY_PATH.read_text())
    assert set(raw) == {"breakdowns", "quizzes"}


def test_rotation_alternates_and_uses_library_in_order():
    history = {"posts": []}
    seen = []
    for _ in range(34):  # beyond the library (28) into generated content
        it = next_item(history)
        seen.append(it)
        history["posts"].append({"id": it["id"], "hash": it["hash"], "format": it["format"], "status": "posted"})
    fmts = [i["format"] for i in seen]
    assert fmts == ["breakdown", "quiz"] * 17
    assert [i["id"] for i in seen[:28:2]] == [f"b{n:02d}" for n in range(1, 15)]
    assert [i["id"] for i in seen[1:28:2]] == [f"q{n:02d}" for n in range(1, 15)]
    assert all(i["id"].startswith("gen-") for i in seen[28:])
    assert len({i["hash"] for i in seen}) == len(seen)  # never repeats


def test_failed_posts_are_retried():
    history = {"posts": [{"id": "b01", "hash": LIB["breakdown"][0]["hash"], "format": "breakdown",
                          "status": "failed"}]}
    assert next_format(history) == "breakdown"
    assert next_item(history)["id"] == "b01"


@pytest.mark.parametrize("i", range(12))
def test_captions(i):
    item = ALL[i % len(ALL)]
    cap = build_caption(item, i)
    assert len(cap) < 2000
    assert CLUB_LINE in cap
    tags = re.findall(r"#\w+", cap)
    assert 4 <= len(tags) <= 6 and set(tags) <= set(HASHTAGS) and len(set(tags)) == len(tags)
    assert not re.search(r"https?://|www\.|t\.me", cap)
    assert compliance_problems(cap) == []


def test_compliance_catches_money_talk():
    for bad in ["Deposit now", "Get rakeback", "real money games", "fast payouts", "visit t.me/club",
                "win $100"]:
        assert compliance_problems(bad), bad
    assert compliance_problems("100bb cash  |  You: Button") == []
