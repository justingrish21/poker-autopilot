"""Load, normalize and validate content items (library + generated)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .cards import is_valid_card

LIBRARY_PATH = Path(__file__).with_name("library.json")
DEFAULT_QUIZ_HOOK = "Can you get this right?"

# Words that would make the account look like real-money gambling promotion.
# "cash game" / "100bb cash" as strategy context is fine and is not matched here.
BANNED_PATTERNS = [
    r"real[\s-]*money", r"deposit", r"rake\s*back", r"payouts?", r"\bpay\s*out", r"withdraw",
    r"cash[\s-]*out", r"cash\s+prizes?", r"win\s+cash", r"for\s+money", r"\$", r"\busd\b",
    r"bitcoin", r"crypto", r"casino", r"sign[\s-]*up\s+bonus", r"bonus\s+code", r"gambl",
]
URL_PATTERNS = [r"https?://", r"www\.", r"\bt\.me\b", r"\.(com|net|org|io|gg|me|dev|app)\b"]


def compliance_problems(text: str) -> list[str]:
    problems = []
    low = text.lower()
    for p in BANNED_PATTERNS:
        if re.search(p, low):
            problems.append(f"banned phrase /{p}/ in: {text!r}")
    for p in URL_PATTERNS:
        if re.search(p, low):
            problems.append(f"link/URL /{p}/ in: {text!r}")
    return problems


def item_texts(item: dict) -> list[str]:
    keys = ["hook", "setup", "action", "play", "q", "explain", "caption"]
    out = [item[k] for k in keys if item.get(k)]
    out += list(item.get("why", [])) + list(item.get("options", []))
    out += [v for v in (item.get("captions") or {}).values() if v]
    out += [s["name"] for s in item.get("seats", [])]
    return out


def content_hash(item: dict) -> str:
    """Hash of what the viewer sees (ignores id), so identical content never reposts."""
    keys = ["format", "hook", "setup", "hero", "board", "villain", "action", "play", "why",
            "q", "options", "answer", "explain"]
    payload = {k: item.get(k) for k in keys}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def normalize(item: dict, fmt: str) -> dict:
    it = dict(item)
    it["format"] = fmt
    it.setdefault("hero", [])
    it.setdefault("board", [])
    it.setdefault("villain", [])
    if fmt == "quiz":
        it.setdefault("hook", DEFAULT_QUIZ_HOOK)
    it["hash"] = content_hash(it)
    return it


def validate_item(item: dict) -> list[str]:
    errs = []
    fmt = item.get("format")
    cards = list(item.get("hero", [])) + list(item.get("board", [])) + list(item.get("villain", []))
    for c in cards:
        if not is_valid_card(c):
            errs.append(f"{item.get('id')}: invalid card {c!r}")
    if len(set(cards)) != len(cards):
        errs.append(f"{item.get('id')}: duplicate cards {cards}")
    if len(item.get("hero", [])) not in (0, 2):
        errs.append(f"{item.get('id')}: hero must have 0 or 2 cards")
    if len(item.get("villain", [])) not in (0, 2):
        errs.append(f"{item.get('id')}: villain must have 0 or 2 cards")
    if len(item.get("board", [])) not in (0, 3, 4, 5):
        errs.append(f"{item.get('id')}: board must have 0, 3, 4 or 5 cards")
    if fmt == "breakdown":
        for k in ("hook", "setup", "action", "play", "why"):
            if not item.get(k):
                errs.append(f"{item.get('id')}: missing {k}")
        if not 2 <= len(item.get("why", [])) <= 3:
            errs.append(f"{item.get('id')}: need 2-3 reasons")
    elif fmt == "quiz":
        for k in ("q", "options", "explain"):
            if not item.get(k):
                errs.append(f"{item.get('id')}: missing {k}")
        opts = item.get("options", [])
        if not 2 <= len(opts) <= 3:
            errs.append(f"{item.get('id')}: need 2-3 options")
        if len(set(opts)) != len(opts):
            errs.append(f"{item.get('id')}: duplicate options")
        if not isinstance(item.get("answer"), int) or not 0 <= item["answer"] < len(opts):
            errs.append(f"{item.get('id')}: bad answer index")
    elif fmt == "allin":
        if len(item.get("hero", [])) != 2 or len(item.get("villain", [])) != 2 or len(item.get("board", [])) != 5:
            errs.append(f"{item.get('id')}: all-in story needs hero, villain and a 5-card board")
        if not item.get("hook") or len(item.get("seats", [])) != 5:
            errs.append(f"{item.get('id')}: missing hook or seats")
        if item.get("seats") and item["seats"][4]["name"] != "PokerPilot":
            errs.append(f"{item.get('id')}: hero seat must be PokerPilot")
    else:
        errs.append(f"{item.get('id')}: unknown format {fmt!r}")
    for t in item_texts(item):
        errs.extend(compliance_problems(t))
    return errs


def load_library(path: Path = LIBRARY_PATH) -> dict[str, list[dict]]:
    data = json.loads(Path(path).read_text())
    return {
        "breakdown": [normalize(x, "breakdown") for x in data.get("breakdowns", [])],
        "quiz": [normalize(x, "quiz") for x in data.get("quizzes", [])],
    }
