#!/usr/bin/env python3
"""Print your connected Post for Me social accounts and their ids.

    POST_FOR_ME_API_KEY=pfm_xxx python scripts/list_accounts.py
    POST_FOR_ME_API_KEY=pfm_xxx python scripts/list_accounts.py --platform tiktok

Copy the id of your TikTok account into the PFM_TIKTOK_ACCOUNT_ID GitHub secret.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from publish.postforme import PostForMe, PostForMeError  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", help="filter, e.g. tiktok or tiktok_business")
    args = ap.parse_args()
    key = os.environ.get("POST_FOR_ME_API_KEY", "").strip()
    if not key:
        print("Set POST_FOR_ME_API_KEY first, e.g.\n  POST_FOR_ME_API_KEY=pfm_xxx python scripts/list_accounts.py")
        return 2
    try:
        accounts = PostForMe(key).list_accounts(args.platform)
    except PostForMeError as e:
        print(f"Request failed: {e}")
        return 1
    if not accounts:
        print("No connected accounts. Connect TikTok in the Post for Me dashboard first.")
        return 1
    print(f"{'PLATFORM':<18} {'USERNAME':<28} {'STATUS':<13} ID")
    for a in accounts:
        print(f"{a.get('platform', ''):<18} {str(a.get('username') or ''):<28} {a.get('status', ''):<13} {a.get('id')}")
    tiktok = [a for a in accounts if str(a.get("platform", "")).startswith("tiktok")]
    if tiktok:
        print(f"\nYour TikTok account id (PFM_TIKTOK_ACCOUNT_ID): {tiktok[0]['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
