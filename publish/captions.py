"""TikTok captions: item caption + CTA + club line + 4-6 rotating hashtags. No links."""
from __future__ import annotations

from content.library import compliance_problems

HASHTAGS = ["#poker", "#pokerstrategy", "#pokertips", "#texasholdem", "#pokerquiz",
            "#learnpoker", "#pokerhands", "#holdem"]
CLUB_LINE = "Free play-money club — link in bio"
QUIZ_CTAS = [
    "Drop your answer in the comments before the reveal.",
    "Comment A, B or C. No cheating!",
    "Tag the friend who always gets this wrong.",
    "Got it right? Come prove it at the tables.",
]
BREAKDOWN_CTAS = [
    "Would you have made the right play? Tell me below.",
    "Save this for your next session.",
    "Send this to the friend who always calls.",
    "Think you'd play it better? Come prove it.",
]
ALLIN_CTAS = [
    "Would you have called? Be honest.",
    "Tag the friend who always gets lucky on the river.",
    "Lucky or good? Tell me below.",
    "Think you'd run better? Come prove it.",
]
MAX_LEN = 2000


def template_caption(item: dict) -> str:
    if item["format"] == "quiz":
        return item.get("q", "Poker quiz time.")
    return f"{item.get('hook', 'Hand breakdown')}. Here's the play."


def hashtags_for(index: int, count: int = 5) -> list[str]:
    """#poker always, plus a rotating window of the others (4-6 total)."""
    count = max(4, min(6, count))
    others = HASHTAGS[1:]
    start = (index * 3) % len(others)
    picked = [others[(start + i) % len(others)] for i in range(count - 1)]
    return ["#poker"] + picked


def cta_options(fmt: str) -> list[str]:
    return {"quiz": QUIZ_CTAS, "allin": ALLIN_CTAS}.get(fmt, BREAKDOWN_CTAS)


def build_caption(item: dict, index: int, cta: str | None = None) -> str:
    base = (item.get("caption") or template_caption(item)).strip()
    ctas = cta_options(item["format"])
    cta = cta or ctas[index % len(ctas)]
    tags = " ".join(hashtags_for(index, 4 + index % 3))
    caption = f"{base}\n\n{cta}\n{CLUB_LINE}\n\n{tags}"
    if len(caption) > MAX_LEN:
        caption = caption[:MAX_LEN]
    problems = compliance_problems(caption)
    if problems:
        raise ValueError("caption failed compliance check: " + "; ".join(problems))
    return caption
