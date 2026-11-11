"""Minimal Post for Me REST client (stdlib only).

Endpoints and field names were taken from the official `post-for-me` Python SDK
(v1.16, generated from the API's OpenAPI spec):

  auth            Authorization: Bearer <POST_FOR_ME_API_KEY>
  base URL        https://api.postforme.dev
  POST /v1/media/create-upload-url      -> {"upload_url", "media_url"}
  PUT  <upload_url>  (raw file bytes, Content-Type: video/mp4)
  POST /v1/social-posts                 body: caption, social_accounts[], media[{url}],
                                        platform_configurations{tiktok{...}}, external_id
                                        -> SocialPost {id, status: draft|scheduled|processing|processed}
  GET  /v1/social-posts/{id}
  GET  /v1/social-posts?external_id=... -> {"data": [...], "meta": {...}}
  GET  /v1/social-post-results?post_id=...  -> {"data": [{success, error, platform_data{id,url}, ...}]}
  GET  /v1/social-accounts?platform=...     -> {"data": [{id, platform, username, status, ...}]}
  GET  /v1/social-account-feeds/{account}?expand=metrics -> {"data": [{social_post_id, platform_url, metrics}]}
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = os.environ.get("POST_FOR_ME_BASE_URL", "https://api.postforme.dev")
USER_AGENT = "poker-autopilot/1.0"

# TikTok options: public, comments/duet/stitch on, not AI-generated (code-rendered graphics),
# not branded content, posted directly (not as an in-app draft).
TIKTOK_CONFIG = {
    "privacy_status": "public",
    "allow_comment": True,
    "allow_duet": True,
    "allow_stitch": True,
    "is_ai_generated": False,
    "disclose_your_brand": False,
    "disclose_branded_content": False,
    "is_draft": False,
}


class PostForMeError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None, retryable: bool = False):
        super().__init__(msg)
        self.status = status
        self.retryable = retryable


def with_retries(fn, what: str, attempts: int = 3, base_delay: float = 4.0, log=print, before_retry=None):
    """Call fn() up to `attempts` times with exponential backoff on retryable errors."""
    last = None
    for i in range(attempts):
        try:
            if i and before_retry:
                found = before_retry()
                if found is not None:
                    return found
            return fn()
        except PostForMeError as e:
            last = e
            if not e.retryable or i == attempts - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = PostForMeError(f"{what}: network error: {e}", retryable=True)
            if i == attempts - 1:
                raise last from e
        delay = base_delay * (2 ** i)
        log(f"  {what} failed ({last}); retry {i + 2}/{attempts} in {delay:.0f}s")
        time.sleep(delay)
    raise last  # pragma: no cover


class PostForMe:
    def __init__(self, api_key: str, base_url: str = BASE_URL, timeout: float = 60):
        if not api_key:
            raise PostForMeError("POST_FOR_ME_API_KEY is not set")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # -- low level ----------------------------------------------------------
    def request(self, method: str, path: str, body: dict | None = None, params: dict | None = None):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", USER_AGENT)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            retryable = e.code in (408, 409, 425, 429) or e.code >= 500
            raise PostForMeError(f"{method} {path} -> HTTP {e.code}: {detail}", e.code, retryable) from e
        return json.loads(raw) if raw else {}

    # -- API ----------------------------------------------------------------
    def list_accounts(self, platform: str | None = None) -> list[dict]:
        out, offset = [], 0
        while True:
            params = {"limit": 100, "offset": offset}
            if platform:
                params["platform"] = platform
            page = self.request("GET", "/v1/social-accounts", params=params)
            data = page.get("data", [])
            out += data
            meta = page.get("meta") or {}
            if not data or not meta.get("next"):
                return out
            offset += len(data)

    def create_upload_url(self) -> dict:
        return self.request("POST", "/v1/media/create-upload-url")

    def upload_file(self, upload_url: str, path: Path, content_type: str = "video/mp4") -> None:
        data = Path(path).read_bytes()
        req = urllib.request.Request(upload_url, data=data, method="PUT")
        req.add_header("Content-Type", content_type)
        req.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            raise PostForMeError(f"PUT upload -> HTTP {e.code}: {detail}", e.code,
                                 e.code in (408, 429) or e.code >= 500) from e

    def create_post(self, caption: str, account_id: str, media_url: str, external_id: str) -> dict:
        body = {
            "caption": caption,
            "social_accounts": [account_id],
            "media": [{"url": media_url}],
            # Set for both TikTok account types; only the one matching the account applies.
            "platform_configurations": {"tiktok": TIKTOK_CONFIG, "tiktok_business": TIKTOK_CONFIG},
            "external_id": external_id,
        }
        return self.request("POST", "/v1/social-posts", body=body)

    def find_post_by_external_id(self, external_id: str) -> dict | None:
        page = self.request("GET", "/v1/social-posts", params={"external_id": external_id, "limit": 5})
        data = page.get("data") or []
        return data[0] if data else None

    def get_post(self, post_id: str) -> dict:
        return self.request("GET", f"/v1/social-posts/{urllib.parse.quote(post_id)}")

    def get_results(self, post_id: str) -> list[dict]:
        page = self.request("GET", "/v1/social-post-results", params={"post_id": post_id, "limit": 20})
        return page.get("data") or []

    def feed(self, account_id: str, max_pages: int = 10, page_size: int = 50):
        """Yield the account's platform posts with metrics (newest first)."""
        cursor = None
        for _ in range(max_pages):
            params = {"expand": "metrics", "limit": page_size}
            if cursor:
                params["cursor"] = cursor
            page = self.request("GET", f"/v1/social-account-feeds/{urllib.parse.quote(account_id)}", params=params)
            for item in page.get("data") or []:
                yield item
            meta = page.get("meta") or {}
            if not meta.get("has_more") or not meta.get("cursor") or meta.get("cursor") == cursor:
                return
            cursor = meta["cursor"]

    # -- high level ---------------------------------------------------------
    def upload_media(self, path: Path, log=print) -> str:
        """Upload flow: get a signed URL, PUT the file, return the public media_url."""
        def attempt():
            u = self.create_upload_url()
            if not u.get("upload_url") or not u.get("media_url"):
                raise PostForMeError(f"unexpected create-upload-url response: {u}")
            self.upload_file(u["upload_url"], path)
            return u["media_url"]
        return with_retries(attempt, "media upload", log=log)

    def publish(self, caption: str, account_id: str, media_url: str, external_id: str, log=print) -> dict:
        """Create the post, retrying safely: before a retry, check whether the earlier
        attempt actually created it (same external_id) so we never double-post."""
        return with_retries(
            lambda: self.create_post(caption, account_id, media_url, external_id),
            "create post", log=log,
            before_retry=lambda: self._safe_find(external_id),
        )

    def _safe_find(self, external_id: str):
        try:
            return self.find_post_by_external_id(external_id)
        except Exception:
            return None

    def wait_for_result(self, post_id: str, account_id: str | None = None, timeout_s: float = 900,
                        interval_s: float | None = None, log=print) -> dict:
        """Poll until the platform result appears. Returns
        {"state": "posted"|"failed"|"timeout", "url", "platform_id", "error", "post_status"}."""
        interval_s = interval_s or float(os.environ.get("PFM_POLL_SECONDS", "15"))
        deadline = time.time() + timeout_s
        status = None
        while True:
            try:
                results = self.get_results(post_id)
                mine = [r for r in results if not account_id or r.get("social_account_id") == account_id] or results
                if mine:
                    r = mine[0]
                    pd = r.get("platform_data") or {}
                    if r.get("success"):
                        return {"state": "posted", "url": pd.get("url"), "platform_id": pd.get("id"),
                                "error": None, "post_status": "processed"}
                    return {"state": "failed", "url": None, "platform_id": None,
                            "error": json.dumps(r.get("error"))[:1000], "post_status": "processed"}
                status = self.get_post(post_id).get("status")
                log(f"  post {post_id}: status={status}, waiting for TikTok result...")
            except PostForMeError as e:
                if not e.retryable:
                    raise
                log(f"  poll error (will keep trying): {e}")
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                log(f"  poll network error (will keep trying): {e}")
            if time.time() >= deadline:
                return {"state": "timeout", "url": None, "platform_id": None, "error": None,
                        "post_status": status}
            time.sleep(interval_s)
