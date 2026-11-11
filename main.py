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


def reconcile_pending(client: PostForMe, history: dict, account_id: str | None) -> bool:
    """Update entries left 'processing' by an earlier run that timed out while polling."""
    changed = False
    for e in history["posts"]:
        if e.get("status") != "processing" or not e.get("post_id"):
            continue
        try:
            res = client.wait_for_result(e["post_id"], account_id, timeout_s=0, log=log)
        except PostForMeError as ex:
            log(f"  could not reconcile {e['post_id']}: {ex}")
            continue
        if res["state"] in ("posted", "failed"):
            e["status"] = res["state"]
            e["url"] = res["url"]
            e["error"] = res["error"]
            e["updated_at"] = now_iso()
            changed = True
            log(f"  reconciled {e['id']} -> {res['state']}")
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


def sync_and_report(client: PostForMe, history: dict, account_id: str) -> None:
    try:
        learning.sync_metrics(client, history, account_id, log=log)
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

    if (not args.dry_run or args.report_only) and (not api_key or not account_id):
        gh_error("POST_FOR_ME_API_KEY and PFM_TIKTOK_ACCOUNT_ID must be set (or use --dry-run).")
        return 2

    history = load_history()
    client = PostForMe(api_key) if not args.dry_run else None
    if args.report_only:
        client = PostForMe(api_key)
    if client and reconcile_pending(client, history, account_id):
        save_history(history)
    if client:
        log("Syncing TikTok metrics...")
        sync_and_report(client, history, account_id)
        if args.report_only:
            log(f"Wrote {REPORT_PATH}")
            return 0

    rng = random.Random()
    if args.item:
        item = find_item(args.item)
    else:
        fmt = args.format or planned_format(history)
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
        f"{info['vcodec']}/{info['pix_fmt']} + {info['audio']}, music={meta['music'] or 'silent'}, "
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
        "music": "beat" if meta["music"] else "silent", "hook": item.get("hook"),
    }
    try:
        log("Uploading media to Post for Me...")
        media_url = client.upload_media(mp4, log=log)
        log("Creating TikTok post...")
        post = client.publish(caption, account_id, media_url, external_id, log=log)
        entry["post_id"] = post.get("id")
        log(f"  post id {entry['post_id']} (status {post.get('status')})")
        res = client.wait_for_result(entry["post_id"], account_id, log=log)
    except PostForMeError as e:
        entry.update(status="failed", error=str(e)[:1000], posted_at=None)
        history["posts"].append(entry)
        save_history(history)
        gh_error(f"Posting failed after retries: {e}")
        return 1

    entry["updated_at"] = now_iso()
    if res["state"] == "posted":
        entry.update(status="posted", posted_at=now_iso(), url=res["url"], platform_id=res["platform_id"])
        history["posts"].append(entry)
        save_history(history)
        log(f"Posted! {res['url'] or ''}")
        return 0
    if res["state"] == "timeout":
        # The post exists and is still processing. Count it as used (never double-post);
        # the next run re-checks it and frees the content if TikTok rejected it.
        entry.update(status="processing", posted_at=now_iso())
        history["posts"].append(entry)
        save_history(history)
        print(f"::warning::Post {entry['post_id']} still processing after polling; will re-check next run.")
        return 0
    entry.update(status="failed", error=res["error"])
    history["posts"].append(entry)
    save_history(history)
    gh_error(f"TikTok rejected post {entry['post_id']}: {res['error']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
