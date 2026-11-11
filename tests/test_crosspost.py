"""TikTok + Instagram cross-posting: per-platform results and combined metrics."""
from __future__ import annotations

from content import learning
from main import apply_results, overall_status

ACC = {"tiktok": "spc_tt", "instagram": "spc_ig"}


def r(state, url=None, err=None):
    return {"state": state, "url": url, "platform_id": None, "error": err}


def test_overall_status_rules():
    assert overall_status({"tiktok": r("posted"), "instagram": r("posted")}) == "posted"
    assert overall_status({"tiktok": r("failed"), "instagram": r("posted")}) == "posted"   # live on IG: never repost
    assert overall_status({"tiktok": r("timeout"), "instagram": r("failed")}) == "processing"
    assert overall_status({"tiktok": r("failed"), "instagram": r("failed")}) == "failed"   # retried later


def test_apply_results_prefers_tiktok_url_and_collects_errors():
    e = {}
    apply_results(e, ACC, {"spc_tt": r("posted", "https://tiktok/x"), "spc_ig": r("failed", err="bad ratio")})
    assert e["status"] == "posted" and e["url"] == "https://tiktok/x"
    assert "instagram: bad ratio" in e["error"]
    apply_results(e, {"instagram": "spc_ig"}, {"spc_ig": r("posted", "https://ig/x")})  # later reconcile
    assert e["platforms"]["instagram"]["state"] == "posted" and e["error"] is None


class TwoFeeds:
    def feed(self, account_id, max_pages=10):
        if account_id == "spc_tt":
            yield {"social_post_id": "sp_1", "platform_url": "https://tiktok/v/1",
                   "metrics": {"view_count": 1000, "like_count": 50, "comment_count": 5, "share_count": 2}}
        else:
            yield {"social_post_id": "sp_1", "platform_url": "https://instagram/p/1",
                   "metrics": {"views": 400, "likes": 30, "comments": 3, "shares": 1, "saved": 4,
                               "follows": 2, "profile_visits": 9}}


def test_sync_combines_platforms():
    h = {"posts": [{"id": "q01", "status": "posted", "post_id": "sp_1"}]}
    n = learning.sync_metrics(TwoFeeds(), h, ACC, log=lambda *_: None)
    e = h["posts"][0]
    assert n == 1
    assert e["metrics_by_platform"]["tiktok"]["views"] == 1000
    assert e["metrics_by_platform"]["instagram"]["profile_views"] == 9
    assert e["metrics"]["views"] == 1400 and e["metrics"]["comments"] == 8 and e["metrics"]["follows"] == 2
    assert e["urls"] == {"tiktok": "https://tiktok/v/1", "instagram": "https://instagram/p/1"}
