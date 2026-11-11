"""The learner: metric parsing, scoring, Thompson sampling, rotation guardrails, sync, report."""
from __future__ import annotations

import random
from collections import Counter
from datetime import datetime, timedelta, timezone

from content import learning
from content.library import load_library
from content.rotation import next_format, next_item

NOW = datetime(2026, 12, 1, tzinfo=timezone.utc)


def post(i, features, views, comments=0, shares=0, likes=0, age_h=72, fmt="breakdown"):
    t = (NOW - timedelta(hours=age_h)).isoformat()
    return {"id": f"x{i}", "hash": f"h{i}", "format": fmt, "status": "posted", "post_id": f"sp_{i}",
            "posted_at": t, "features": dict(features, format=fmt),
            "metrics": {"views": views, "likes": likes, "comments": comments, "shares": shares}}


def test_normalize_both_tiktok_shapes():
    personal = learning.normalize_metrics({"view_count": 900, "like_count": 50, "comment_count": 7, "share_count": 3})
    business = learning.normalize_metrics({"video_views": 900, "likes": 50, "comments": 7, "shares": 3,
                                           "profile_views": 12, "new_followers": 4, "website_clicks": 2})
    assert personal["views"] == business["views"] == 900
    assert personal["comments"] == business["comments"] == 7
    assert business["follows"] == 4 and business["link_clicks"] == 2
    assert learning.club_score(business) > learning.club_score(personal)
    assert learning.normalize_metrics({}) is None


def test_shares_and_comments_beat_raw_views():
    lurkers = {"views": 2000, "likes": 20}
    engaged = {"views": 800, "likes": 20, "comments": 15, "shares": 10}
    assert learning.club_score(engaged) > learning.club_score(lurkers)


def test_no_learning_until_enough_mature_posts():
    h = {"posts": [post(i, {"teaser": "A"}, 100) for i in range(learning.MIN_MATURE_TO_LEARN - 1)]}
    assert learning.choose(h, "teaser", ["A", "B"], random.Random(1), NOW) is None
    young = {"posts": [post(i, {"teaser": "A"}, 100, age_h=5) for i in range(20)]}
    assert learning.choose(young, "teaser", ["A", "B"], random.Random(1), NOW) is None


def test_thompson_prefers_winner_but_keeps_exploring():
    posts = []
    for i in range(30):
        arm = "A" if i % 2 else "B"
        posts.append(post(i, {"teaser": arm}, 500, comments=30 if arm == "A" else 1, shares=5 if arm == "A" else 0))
    h = {"posts": posts}
    rng = random.Random(7)
    picks = Counter(learning.choose(h, "teaser", ["A", "B", "C"], rng, NOW) for _ in range(600))
    assert picks["A"] > picks["B"] * 3          # strongly prefers the winner
    assert picks["C"] > 0                       # untested option still gets tried


def test_format_never_three_in_a_row():
    posts = [post(i, {}, 1000 if i % 2 else 10, comments=20 if i % 2 else 0,
                  fmt="quiz" if i % 2 else "breakdown") for i in range(20)]
    posts += [post(100, {}, 5, fmt="quiz"), post(101, {}, 5, fmt="quiz")]
    h = {"posts": posts}
    for s in range(50):
        assert next_format(h, random.Random(s)) != "quiz"


def test_kind_learning_after_library(monkeypatch):
    lib = load_library()
    posts = [{"id": it["id"], "hash": it["hash"], "format": it["format"], "status": "posted"}
             for fmt in ("breakdown", "quiz") for it in lib[fmt]]
    for i in range(24):
        kind = "combos" if i % 3 == 0 else "pot_odds"
        good = kind == "combos"
        posts.append(post(i, {"kind": kind}, 900, comments=25 if good else 0, shares=8 if good else 0, fmt="quiz"))
    h = {"posts": posts}
    monkeypatch.setattr(learning, "datetime", _FrozenDatetime)
    kinds = Counter(next_item(h, "quiz", rng=random.Random(s))["kind"] for s in range(40))
    assert kinds["combos"] > kinds["pot_odds"]


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


class FakeClient:
    def feed(self, account_id, max_pages=10):
        yield {"social_post_id": "sp_1", "platform_url": "https://www.tiktok.com/@p/video/1",
               "metrics": {"view_count": 1234, "like_count": 80, "comment_count": 9, "share_count": 4}}
        yield {"social_post_id": "sp_other", "metrics": {"view_count": 5}}


def test_sync_metrics_and_report():
    h = {"posts": [{"id": "b01", "hash": "h", "format": "breakdown", "status": "processing", "post_id": "sp_1",
                    "posted_at": (NOW - timedelta(hours=80)).isoformat(), "title": "Stop limping",
                    "features": {"format": "breakdown", "kind": "library", "teaser": "T"}}]}
    n = learning.sync_metrics(FakeClient(), h, "spc_x", log=lambda *_: None)
    e = h["posts"][0]
    assert n == 1 and e["metrics"]["views"] == 1234 and e["status"] == "posted"
    assert e["url"].endswith("/video/1") and e["club_score"] > 0
    md = learning.report(h, NOW)
    assert "Performance report" in md and "Stop limping" in md and "Content type" in md
