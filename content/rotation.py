"""Pick what to post next and keep state/history.json.

Rules:
  * Formats alternate: breakdown, quiz, breakdown, quiz...
  * Library items are used first, in order; then generated items.
  * Nothing is reposted: an item counts as used if its id OR content hash appears in
    history with any status except "failed" (failed posts are retried later).
"""
from __future__ import annotations

import json
import os
import random
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .allin import ALLIN_KINDS
from .generators import BREAKDOWN_KINDS, QUIZ_KINDS, generate, generated_id
from .learning import choose
from .library import load_library

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / "state" / "history.json"
FORMATS = ("breakdown", "quiz", "allin")
# What posts automatically each day (Detroit time): first post = quiz, second = all-in story.
DAILY_PLAN = ("quiz", "allin")
LOCAL_TZ = "America/Detroit"
USED_STATUSES = {"posted", "processing"}  # "failed" entries do not block reuse


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def local_date(ts: datetime):
    try:
        from zoneinfo import ZoneInfo
        return ts.astimezone(ZoneInfo(LOCAL_TZ)).date()
    except Exception:  # no tz database: Eastern Standard Time is close enough for "which day"
        from datetime import timedelta
        return (ts.astimezone(timezone.utc) - timedelta(hours=5)).date()


def planned_format(history: dict, now: datetime | None = None) -> str:
    """Today's next format from DAILY_PLAN: whatever hasn't been posted yet today.
    Robust to late or failed runs: a day never gets two quizzes before its all-in story."""
    now = now or datetime.now(timezone.utc)
    today = local_date(now)
    posted_today = []
    for p in history["posts"]:
        if p.get("status") not in USED_STATUSES:
            continue
        ts = p.get("posted_at") or p.get("created_at")
        try:
            when = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if local_date(when) == today:
            posted_today.append(p.get("format"))
    for fmt in DAILY_PLAN:
        if fmt not in posted_today:
            return fmt
    return DAILY_PLAN[len(posted_today) % len(DAILY_PLAN)]  # extra manual runs keep alternating


def load_history(path: Path = HISTORY_PATH) -> dict:
    if not Path(path).exists():
        return {"posts": []}
    data = json.loads(Path(path).read_text() or "{}")
    data.setdefault("posts", [])
    return data


def save_history(history: dict, path: Path = HISTORY_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(history, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def used_sets(history: dict) -> tuple[set[str], set[str]]:
    ids, hashes = set(), set()
    for p in history["posts"]:
        if p.get("status") in USED_STATUSES:
            ids.add(p.get("id"))
            hashes.add(p.get("hash"))
    return ids, hashes


KINDS = {"breakdown": BREAKDOWN_KINDS, "quiz": QUIZ_KINDS, "allin": ALLIN_KINDS}


def next_format(history: dict, rng: random.Random | None = None) -> str:
    """Rotate breakdown -> quiz -> all-in story until there's data; then let results
    pick the format, but never post the same format more than twice in a row."""
    used = [p.get("format") for p in history["posts"] if p.get("status") in USED_STATUSES
            and p.get("format") in FORMATS]
    cycle = FORMATS[(FORMATS.index(used[-1]) + 1) % len(FORMATS)] if used else FORMATS[0]
    learned = choose(history, "format", list(FORMATS), rng) if rng else None
    if learned is None:
        return cycle
    if len(used) >= 2 and used[-1] == used[-2] == learned:
        others = [f for f in FORMATS if f != learned]
        return choose(history, "format", others, rng) or cycle
    return learned


def next_item(history: dict, fmt: str | None = None, max_scan: int = 5000,
              rng: random.Random | None = None) -> dict:
    """Library first (in order), then generated content. Once there's data, the
    generated content type (pot odds, outs, equity...) is picked by past results."""
    fmt = fmt or next_format(history, rng)
    ids, hashes = used_sets(history)
    for item in load_library().get(fmt, []):
        if item["id"] not in ids and item["hash"] not in hashes:
            return item
    kinds = KINDS[fmt]
    kind = choose(history, "kind", list(kinds), rng) if rng else None
    for n in range(max_scan):
        if kind is not None and kinds[n % len(kinds)] != kind:
            continue
        if generated_id(fmt, n) in ids:
            continue  # cheap skip without generating
        item = generate(fmt, n)
        if item["hash"] not in hashes:
            return item
    raise RuntimeError(f"no unused {fmt} content found in {max_scan} candidates")


def find_item(item_id: str) -> dict:
    """Look up a library item by id, or build a generated one from 'gen-<fmt>-<n>'."""
    lib = load_library()
    for fmt in FORMATS:
        for it in lib.get(fmt, []):
            if it["id"] == item_id:
                return it
    parts = item_id.split("-")
    if len(parts) == 3 and parts[0] == "gen" and parts[1] in FORMATS:
        return generate(parts[1], int(parts[2]))
    raise KeyError(f"unknown item id {item_id!r}")


def history_entry(item: dict, **fields) -> dict:
    e = {
        "id": item["id"],
        "hash": item["hash"],
        "format": item["format"],
        "kind": item.get("kind", "library"),
        "title": item.get("hook") if item["format"] == "breakdown" else item.get("q"),
        "created_at": now_iso(),
    }
    e.update(fields)
    return e
