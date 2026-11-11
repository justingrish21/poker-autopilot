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

from .generators import BREAKDOWN_KINDS, QUIZ_KINDS, generate, generated_id
from .learning import choose
from .library import load_library

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / "state" / "history.json"
FORMATS = ("breakdown", "quiz")
USED_STATUSES = {"posted", "processing"}  # "failed" entries do not block reuse


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


KINDS = {"breakdown": BREAKDOWN_KINDS, "quiz": QUIZ_KINDS}


def next_format(history: dict, rng: random.Random | None = None) -> str:
    """Alternate formats until there's data; then let results pick the format,
    but never post the same format more than twice in a row."""
    used = [p.get("format") for p in history["posts"] if p.get("status") in USED_STATUSES
            and p.get("format") in FORMATS]
    alternate = ("quiz" if used[-1] == "breakdown" else "breakdown") if used else "breakdown"
    learned = choose(history, "format", list(FORMATS), rng) if rng else None
    if learned is None:
        return alternate
    if len(used) >= 2 and used[-1] == used[-2] == learned:
        return "quiz" if learned == "breakdown" else "breakdown"
    return learned


def next_item(history: dict, fmt: str | None = None, max_scan: int = 5000,
              rng: random.Random | None = None) -> dict:
    """Library first (in order), then generated content. Once there's data, the
    generated content type (pot odds, outs, equity...) is picked by past results."""
    fmt = fmt or next_format(history, rng)
    ids, hashes = used_sets(history)
    for item in load_library()[fmt]:
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
        for it in lib[fmt]:
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
