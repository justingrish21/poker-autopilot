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
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .generators import generate, generated_id
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


def next_format(history: dict) -> str:
    for p in reversed(history["posts"]):
        if p.get("status") in USED_STATUSES and p.get("format") in FORMATS:
            return "quiz" if p["format"] == "breakdown" else "breakdown"
    return "breakdown"


def next_item(history: dict, fmt: str | None = None, max_scan: int = 5000) -> dict:
    fmt = fmt or next_format(history)
    ids, hashes = used_sets(history)
    for item in load_library()[fmt]:
        if item["id"] not in ids and item["hash"] not in hashes:
            return item
    for n in range(max_scan):
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
