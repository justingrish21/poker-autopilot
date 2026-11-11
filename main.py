#!/usr/bin/env python3
"""Poker TikTok Autopilot: pick content -> render MP4 -> upload -> post -> record.

  python main.py                 # normal run (posts to TikTok via Post for Me)
  python main.py --dry-run       # render video + caption into out/, skip posting
  python main.py --dry-run --item q07           # render a specific library item
  python main.py --dry-run --item gen-quiz-00003  # render a specific generated item
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from content import learning
from content.library import validate_item
from content.rotation import (HISTORY_PATH, USED_STATUSES, find_item, history_entry, load_history,
                              next_item, now_iso, planned_format, save_history)
from publish.captions import build_caption, cta_options
from publish.postforme import PostForMe, PostForMeError
from render.video import BREAKDOWN_TAGS, QUIZ_TAGS, pick, render_item

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "out"
REPORT_PATH = ROOT / "state" / "performance.md"


def log(msg: str) -> None:
    print(msg, flush=True)


def gh_error(msg: str) -> None:
    """Loud failure: shows as an error annotation in GitHub Actions."""
    print(f"::error::{msg}" if os.environ.get("GITHUB_ACTIONS") else f"ERROR: {msg}", flush=True)


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt:format=duration",
         "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    a = [s for s in data["streams"] if s["codec_type"] == "audio"]
    num, den = map(int, v["r_frame_rate"].split("/"))
    return {"width": v["width"], "height": v["height"], "fps": num / den, "vcodec": v["codec_name"],
            "pix_fmt": v["pix_fmt"], "audio": a[0]["codec_name"] if a else None,
            "duration": float(data["format"]["duration"])}


def check_video(info: dict) -> list[str]:
    errs = []
    if (info["width"], info["height"]) != (1080, 1920):
        errs.append(f"size {info['width']}x{info['height']}")
    if abs(info["fps"] - 30) > 0.01:
        errs.append(f"fps {info['fps']}")
    if info["vcodec"] != "h264" or info["pix_fmt"] != "yuv420p":
        errs.append(f"video {info['vcodec']}/{info['pix_fmt']}")
    if info["audio"] != "aac":
        errs.append(f"audio {info['audio']}")
    if not 15 <= info["duration"] <= 25:
        errs.append(f"duration {info['duration']:.2f}s")
    return errs


def overall_status(platforms: dict[str, dict]) -> str:
    states = [p["state"] for p in platforms.values()]
    if any(s == "posted" for s in states):
        return "posted"          # live somewhere: never repost this content
    if any(s == "timeout" for s in states):
        return "processing"
    return "failed"


def apply_results(entry: dict, accounts: dict[str, str], results: dict[str, dict]) -> None:
    plats = entry.setdefault("platforms", {})
    for platform, acct in accounts.items():
        if acct in results:
            plats[platform] = results[acct]
    entry["status"] = overall_status(plats)
    first = next((p["url"] for p in plats.values() if p.get("url")), None)
    entry["url"] = (plats.get("tiktok") or {}).get("url") or first
    entry["error"] = "; ".join(f"{k}: {v['error']}" for k, v in plats.items() if v.get("error")) or None
    entry["updated_at"] = now_iso()


def reconcile_pending(client: PostForMe, history: dict, accounts: dict[str, str]) -> bool:
    """Update entries left 'processing' by an earlier run that timed out while polling."""
    changed = False
    for e in history["posts"]:
        if e.get("status") != "processing" or not e.get("post_id"):
            continue
        pending = {p: a for p, a in accounts.items()
                   if (e.get("platforms") or {}).get(p, {}).get("state", "timeout") == "timeout"}
        try:
            res = client.wait_for_results(e["post_id"], list(pending.values()), timeout_s=0, log=log)
        except PostForMeError as ex:
            log(f"  could not reconcile {e['post_id']}: {ex}")
            continue
        before = e.get("status")
        apply_results(e, pending, res)
        if e["status"] != before:
            changed = True
            log(f"  reconciled {e['id']} -> {e['status']}")
    return changed


def time_slot(now: datetime | None = None) -> str:
    """Which daily slot this run is (cron 17:30 UTC = midday ET, 00:30 UTC = evening ET)."""
    h = (now or datetime.now(timezone.utc)).hour
    return "midday" if 12 <= h < 22 else "evening"


def choose_variants(item: dict, history: dict, index: int, rng: random.Random) -> dict:
    """Pick the hook tag and caption CTA: learned from results once
    there's enough data, otherwise a deterministic rotation."""
    tags = {"breakdown": BREAKDOWN_TAGS, "quiz": QUIZ_TAGS}.get(item["format"], ["none"])
    ctas = cta_options(item["format"])
    tag = learning.choose(history, "tag", tags, rng) or pick(tags, item)
    cta = learning.choose(history, "cta", ctas, rng) or ctas[index % len(ctas)]
    return {"tag": tag, "cta": cta}


def sync_and_report(client: PostForMe, history: dict, accounts: dict[str, str]) -> None:
    try:
        learning.sync_metrics(client, history, accounts, log=log)
    except Exception as e:  # metrics must never block posting
        log(f"  metrics sync skipped: {e}")
    save_history(history)
    REPORT_PATH.write_text(learning.report(history) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="render into out/ and skip posting")
    ap.add_argument("--item", help="render/post a specific item id (library id or gen-<format>-<n>)")
    ap.add_argument("--format", choices=["breakdown", "quiz", "allin"], help="force the format for this run")
    ap.add_argument("--no-music", action="store_true", help="ignore music/ and use a silent track")
    ap.add_argument("--report-only", action="store_true",
                    help="only pull metrics and rewrite state/performance.md (no video)")
    args = ap.parse_args(argv)

    handle = os.environ.get("BRAND_HANDLE", "").strip() or None
    api_key = os.environ.get("POST_FOR_ME_API_KEY", "").strip()
    account_id = os.environ.get("PFM_TIKTOK_ACCOUNT_ID", "").strip()
    ig_account_id = os.environ.get("PFM_INSTAGRAM_ACCOUNT_ID", "").strip()
    # Every video goes to TikTok, and to Instagram too when an Instagram account id is set.
    accounts = {"tiktok": account_id}
    if ig_account_id and ig_account_id.lower() != "none":
        accounts["instagram"] = ig_account_id

    if (not args.dry_run or args.report_only) and (not api_key or not account_id):
        gh_error("POST_FOR_ME_API_KEY and PFM_TIKTOK_ACCOUNT_ID must be set (or use --dry-run).")
        return 2

    history = load_history()
    client = PostForMe(api_key) if not args.dry_run else None
    if args.report_only:
        client = PostForMe(api_key)
    if client and reconcile_pending(client, history, accounts):
        save_history(history)
    if client:
        log(f"Syncing metrics ({', '.join(accounts)})...")
        sync_and_report(client, history, accounts)
        if args.report_only:
            log(f"Wrote {REPORT_PATH}")
            return 0

    rng = random.Random()
    if args.item:
        item = find_item(args.item)
    else:
        fmt = args.format or planned_format(history)
        if fmt is None:
            log("Today's quiz and all-in story are already posted. Nothing to do this run.")
            return 0
        item = next_item(history, fmt, rng=rng)
    errs = validate_item(item)
    if errs:
        gh_error("content failed validation: " + "; ".join(errs))
        return 3
    index = sum(1 for p in history["posts"] if p.get("status") in USED_STATUSES)
    variants = choose_variants(item, history, index, rng)
    item["tag"] = variants["tag"]
    caption = build_caption(item, index, cta=variants["cta"])
    log(f"Item: {item['id']} ({item['format']}, {item.get('kind', 'library')}) hash={item['hash']}")
    log(f"  learning {'ON' if learning.learning_active(history) else 'warming up'}: tag={variants['tag']!r} "
        f"cta={variants['cta']!r}")

    OUT_DIR.mkdir(exist_ok=True)
    mp4 = OUT_DIR / f"{item['id']}.mp4"
    log("Rendering video...")
    meta = render_item(item, mp4, handle, music=not args.no_music)
    info = probe(mp4)
    log(f"  {mp4.name}: {info['width']}x{info['height']} @ {info['fps']:.0f}fps, {info['duration']:.2f}s, "
        f"{info['vcodec']}/{info['pix_fmt']} + {info['audio']}, music={meta['music'] or 'generated beat'}, "
        f"{mp4.stat().st_size / 1e6:.1f} MB")
    bad = check_video(info)
    if bad:
        gh_error("rendered video is out of spec: " + ", ".join(bad))
        return 4
    (OUT_DIR / f"{item['id']}.txt").write_text(caption + "\n")
    (OUT_DIR / f"{item['id']}.json").write_text(json.dumps(item, indent=2) + "\n")
    log("Caption:\n" + "\n".join("  | " + l for l in caption.splitlines()))

    if args.dry_run:
        log(f"Dry run: wrote {mp4} and its caption. Nothing was posted.")
        return 0

    external_id = f"pa-{item['id']}-{item['hash']}-{len(history['posts'])}"
    entry = history_entry(item, external_id=external_id, music=meta["music"])
    entry["features"] = {
        "format": item["format"], "kind": item.get("kind", "library"), "tag": variants["tag"],
        "cta": variants["cta"], "slot": time_slot(),
        "music": "your beat" if meta["music"] else "generated beat", "hook": item.get("hook"),
    }
    try:
        log("Uploading media to Post for Me...")
        media_url = client.upload_media(mp4, log=log)
        log(f"Creating post for {' + '.join(accounts)}...")
        post = client.publish(caption, list(accounts.values()), media_url, external_id, log=log)
        entry["post_id"] = post.get("id")
        log(f"  post id {entry['post_id']} (status {post.get('status')})")
        res = client.wait_for_results(entry["post_id"], list(accounts.values()), log=log)
    except PostForMeError as e:
        entry.update(status="failed", error=str(e)[:1000], posted_at=None)
        history["posts"].append(entry)
        save_history(history)
        gh_error(f"Posting failed after retries: {e}")
        return 1

    apply_results(entry, accounts, res)
    if entry["status"] in ("posted", "processing"):
        entry["posted_at"] = now_iso()
    history["posts"].append(entry)
    save_history(history)
    for platform, r in entry["platforms"].items():
        log(f"  {platform}: {r['state']} {r.get('url') or ''}")
    failed = [p for p, r in entry["platforms"].items() if r["state"] == "failed"]
    waiting = [p for p, r in entry["platforms"].items() if r["state"] == "timeout"]
    if failed:
        # Loud failure (GitHub emails you). Content that went live on any platform stays used.
        gh_error(f"Post {entry['post_id']} failed on {', '.join(failed)}: {entry.get('error')}")
        return 1
    if waiting:
        print(f"::warning::Post {entry['post_id']} still processing on {', '.join(waiting)}; "
              f"will re-check next run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
