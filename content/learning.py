"""Learn from TikTok results and steer future videos toward what makes people want to play.

How it works
------------
1. Every run pulls the latest metrics for past posts from Post for Me
   (GET /v1/social-account-feeds/{account}?expand=metrics) and stores them in history.
2. Each post gets a "club intent" score. Signals that mean "I want more / I want in"
   (shares, comments, follows, profile views, link clicks) weigh far more than views or likes.
3. Posts are only judged once they're MATURE_HOURS old, and scores are turned into
   percentile ranks so the learner doesn't care about absolute numbers.
4. For each choice the system makes (format, content kind, hook tag, caption CTA) it runs Thompson sampling: options that scored well get picked more,
   untested ones still get tried, and nothing is ever fully abandoned.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

MATURE_HOURS = 48          # judge a video after it has had 2 days to collect views
WINDOW = 90                # learn from the most recent N mature posts (tastes drift)
MIN_MATURE_TO_LEARN = 6    # until then, stick to the plain defaults

# Weights for the club-intent score. A share or follow is worth far more than a view.
WEIGHTS = {
    "views": 0.02, "likes": 1.0, "comments": 4.0, "shares": 6.0, "saves": 3.0,
    "profile_views": 5.0, "follows": 15.0, "link_clicks": 25.0,
}


def _num(*vals):
    for v in vals:
        if isinstance(v, (int, float)):
            return float(v)
    return None


def normalize_metrics(m: dict | None) -> dict | None:
    """Map personal-TikTok and TikTok-Business metric shapes onto one dict."""
    if not m:
        return None
    out = {
        "views": _num(m.get("view_count"), m.get("video_views"), m.get("views")),
        "likes": _num(m.get("like_count"), m.get("likes")),
        "comments": _num(m.get("comment_count"), m.get("comments")),
        "shares": _num(m.get("share_count"), m.get("shares")),
        "saves": _num(m.get("favorites"), m.get("saved")),
        "profile_views": _num(m.get("profile_views")),
        "follows": _num(m.get("new_followers"), m.get("follows")),
        "link_clicks": _num(m.get("website_clicks")),
        "full_watch_rate": _num(m.get("full_video_watched_rate")),
        "avg_watch_s": _num(m.get("average_time_watched")),
    }
    if all(v is None for v in out.values()):
        return None
    return out


def club_score(metrics: dict | None) -> float | None:
    if not metrics:
        return None
    return sum(w * (metrics.get(k) or 0.0) for k, w in WEIGHTS.items())


def _parse(ts: str | None):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def age_hours(entry: dict, now: datetime | None = None) -> float | None:
    t = _parse(entry.get("posted_at"))
    if not t:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - t).total_seconds() / 3600


def mature_posts(history: dict, now: datetime | None = None) -> list[dict]:
    out = []
    for e in history.get("posts", []):
        if e.get("status") != "posted" or not e.get("metrics"):
            continue
        a = age_hours(e, now)
        if a is not None and a >= MATURE_HOURS:
            out.append(e)
    return out[-WINDOW:]


def percentile_rewards(posts: list[dict]) -> dict[str, float]:
    """Post key -> reward in [0, 1] = its percentile rank by club score (ties averaged)."""
    scored = [(club_score(p["metrics"]) or 0.0, i) for i, p in enumerate(posts)]
    if len(scored) == 1:
        return {_key(posts[0]): 0.5}
    order = sorted(scored)
    ranks: dict[int, float] = {}
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and order[j + 1][0] == order[i][0]:
            j += 1
        r = ((i + j) / 2) / (len(order) - 1)
        for k in range(i, j + 1):
            ranks[order[k][1]] = r
        i = j + 1
    return {_key(posts[idx]): r for idx, r in ranks.items()}


def _key(e: dict) -> str:
    return f"{e.get('id')}|{e.get('post_id')}"


def arm_stats(history: dict, dimension: str, now: datetime | None = None) -> dict[str, dict]:
    posts = mature_posts(history, now)
    rewards = percentile_rewards(posts) if posts else {}
    stats: dict[str, dict] = {}
    for p in posts:
        arm = (p.get("features") or {}).get(dimension)
        if arm is None:
            continue
        s = stats.setdefault(str(arm), {"n": 0, "reward": 0.0, "score": 0.0, "views": 0.0})
        s["n"] += 1
        s["reward"] += rewards[_key(p)]
        s["score"] += club_score(p["metrics"]) or 0.0
        s["views"] += (p["metrics"].get("views") or 0.0)
    return stats


def learning_active(history: dict, now: datetime | None = None) -> bool:
    return len(mature_posts(history, now)) >= MIN_MATURE_TO_LEARN


def choose(history: dict, dimension: str, options: list[str], rng: random.Random,
           now: datetime | None = None) -> str | None:
    """Thompson-sample one option. Returns None while there isn't enough data yet."""
    if not options or not learning_active(history, now):
        return None
    stats = arm_stats(history, dimension, now)
    best, best_draw = None, -1.0
    for opt in options:
        s = stats.get(str(opt), {"n": 0, "reward": 0.0})
        a = 1.0 + s["reward"]
        b = 1.0 + (s["n"] - s["reward"])
        draw = rng.betavariate(a, b)
        if draw > best_draw:
            best, best_draw = opt, draw
    return best


# ---------------------------------------------------------------------------
# metrics sync
# ---------------------------------------------------------------------------

def sync_metrics(client, history: dict, account_id: str, max_pages: int = 10, log=print) -> int:
    """Pull metrics for our posts from Post for Me and store them on history entries."""
    by_post = {e["post_id"]: e for e in history.get("posts", []) if e.get("post_id")}
    if not by_post:
        return 0
    updated = 0
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for item in client.feed(account_id, max_pages=max_pages):
        e = by_post.get(item.get("social_post_id"))
        if not e:
            continue
        m = normalize_metrics(item.get("metrics"))
        if m:
            e["metrics"] = m
            e["metrics_at"] = now
            e["club_score"] = round(club_score(m) or 0.0, 2)
            updated += 1
        if item.get("platform_url") and not e.get("url"):
            e["url"] = item["platform_url"]
        if e.get("status") == "processing":
            e["status"] = "posted"
    log(f"  metrics updated for {updated} post(s)")
    return updated


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

DIMENSIONS = [("format", "Format"), ("kind", "Content type"), ("tag", "Hook tag"),
              ("cta", "Caption CTA"), ("slot", "Time slot"),
              ("music", "Music")]


def report(history: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    posts = [e for e in history.get("posts", []) if e.get("status") == "posted"]
    mature = mature_posts(history, now)
    lines = ["# Performance report", "",
             f"_Updated {now.strftime('%Y-%m-%d %H:%M UTC')} automatically by the autopilot._", "",
             f"- Videos posted: **{len(posts)}**",
             f"- Judged so far (older than {MATURE_HOURS}h, with metrics): **{len(mature)}**",
             f"- Learning is **{'ON' if len(mature) >= MIN_MATURE_TO_LEARN else 'warming up'}**"
             + ("" if len(mature) >= MIN_MATURE_TO_LEARN else
                f" (starts after {MIN_MATURE_TO_LEARN} judged videos)"), "",
             "Club-intent score = 0.02 x views + likes + 4 x comments + 6 x shares + 3 x saves"
             " + 5 x profile views + 15 x follows + 25 x link clicks.", ""]
    if mature:
        for dim, title in DIMENSIONS:
            stats = arm_stats(history, dim, now)
            if not stats:
                continue
            lines += [f"## {title}", "", "| Option | Videos | Avg rank (0-1) | Avg score | Avg views |",
                      "|---|---:|---:|---:|---:|"]
            for arm, s in sorted(stats.items(), key=lambda kv: -kv[1]["reward"] / kv[1]["n"]):
                lines.append(f"| {arm} | {s['n']} | {s['reward'] / s['n']:.2f} | {s['score'] / s['n']:.1f} | "
                             f"{s['views'] / s['n']:.0f} |")
            lines.append("")
        ranked = sorted(mature, key=lambda e: -(club_score(e["metrics"]) or 0))
        for title, chunk in (("Top videos", ranked[:5]), ("Weakest videos", ranked[-5:][::-1])):
            lines += [f"## {title}", "", "| Video | Score | Views | Likes | Comments | Shares |",
                      "|---|---:|---:|---:|---:|---:|"]
            for e in chunk:
                m = e["metrics"]
                name = (e.get("title") or e["id"]).replace("|", "/")
                link = f"[{name}]({e['url']})" if e.get("url") else name
                lines.append(f"| {link} | {club_score(m):.1f} | {m.get('views') or 0:.0f} | "
                             f"{m.get('likes') or 0:.0f} | {m.get('comments') or 0:.0f} | {m.get('shares') or 0:.0f} |")
            lines.append("")
    else:
        lines += ["No judged videos yet. Check back a couple of days after the first posts.", ""]
    return "\n".join(lines)
