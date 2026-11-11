# Poker TikTok Autopilot

Fully automatic poker strategy videos for TikTok. Every day at about 12:30 PM and 7:30 PM (Detroit time) a GitHub Action:

1. picks the next piece of content (it alternates hand breakdowns and quizzes, never repeats),
2. renders a 1080x1920 MP4 entirely with code (Python + Pillow + ffmpeg, no AI or paid tools),
3. uploads it to your TikTok through the [Post for Me](https://api.postforme.dev) API,
4. waits until TikTok confirms the post, and records it in `state/history.json`.

Every video ends with: **"Want to play? Free play-money poker club / Link in bio"**.

It costs nothing to run besides your Post for Me plan. GitHub Actions is free for this.

---

## What the videos look like

| Format | Length | Flow |
|---|---|---|
| **Hand breakdown** | 22 s | hook → table, cards slide/flip in → "What's the play?" → **THE PLAY** banner (flash + chip confetti) → 3 reasons → end card |
| **Quiz** | 18 s | hook → question, cards, A/B/C answers → 3-2-1 "Comment your answer" → correct answer glows green (flash + confetti), explanation → end card |

* Dark background, green felt table, real-looking cards, big outlined text.
* Everything important stays inside TikTok's safe zone: nothing in the top 150 px, the bottom 350 px or the right 140 px.
* Built for engagement: punchy hooks, "comment your answer" prompts, a countdown, reveal effects, and a rotating end-card teaser ("Think you'd play it better? Prove it at the tables.").
* Never mentions real money, deposits, rakeback or payouts, in the video or the caption. Every item and caption runs through a compliance check before posting, so the account reads as a poker strategy/education page.

## Content never runs out

* `content/library.json` holds your 14 breakdowns and 14 quizzes. They're used first, in order.
* After that, `content/generators.py` creates unlimited new, mathematically verified content:
  pot odds, outs (counted by enumerating the deck), Rule of 2 and 4 (with the exact %),
  preflop equity (20,000-runout Monte Carlo), combo/blocker counting, and "call or fold this draw?"
  breakdowns (exact equity vs. a real villain hand, compared against the real pot odds).
* `state/history.json` records every post (id, content hash, time, Post for Me post id, status, TikTok URL).
  The same content is never posted twice.

## It learns what makes people want to play

The goal is club sign-ups, so every run:

1. **Pulls TikTok results** for past videos from Post for Me (views, likes, comments, shares;
   with a TikTok **Business** account also profile views, new followers and link clicks).
2. **Scores each video for "club intent"** once it's 48 hours old:
   `0.02 x views + likes + 4 x comments + 6 x shares + 3 x saves + 5 x profile views + 15 x follows + 25 x link clicks`.
   Signals that mean "I want more / I want in" count far more than passive views.
3. **Adjusts automatically** using Thompson sampling (a standard "test and shift" method). After 6 judged
   videos it starts favoring what scores best while still testing alternatives:
   * **Format:** breakdown vs quiz. It never posts the same format 3 times in a row.
   * **Content type:** pot odds, outs, equity, combos, call-or-fold draws. This kicks in once the starter library is used up.
   * **Hook tag** on the opening screen ("POKER QUIZ", "WHAT WOULD YOU DO?"...).
   * **End-card teaser** ("Think you'd play it better? Prove it at the tables."...).
   * **Caption call-to-action.**
4. **Writes `state/performance.md`:** a plain-English report of what's winning, plus the top and weakest videos with links.
   Open it on GitHub any time.

Tip: switch the TikTok account to a free **Business account** (Settings → Account → Switch to Business account).
That unlocks profile views, follows and link clicks, which are the closest signals to "wants to join the club".

---

## Setup (one time, about 10 minutes)

### 1. Post for Me: API key + connect TikTok
1. Sign in to the Post for Me dashboard.
2. Create an **API key** and copy it. It starts with something like `pfm_`.
3. Under social accounts, **connect your TikTok** account.

### 2. Add your API key to GitHub, then find your TikTok account id
1. In this repo: **Settings → Secrets and variables → Actions → New repository secret**.
   Name `POST_FOR_ME_API_KEY`, value = your Post for Me API key.
2. Go to the **Actions** tab → **List Post for Me accounts** → **Run workflow**.
3. Open the finished run. The summary lists your connected accounts; copy the **id** shown for TikTok (it looks like `spc_...`).

(Or on your computer: `POST_FOR_ME_API_KEY=your_key python scripts/list_accounts.py`.)

### 3. Add the GitHub secrets
In this repo: **Settings → Secrets and variables → Actions → New repository secret**. Add:

| Name | Value |
|---|---|
| `POST_FOR_ME_API_KEY` | your Post for Me API key (already added in step 2) |
| `PFM_TIKTOK_ACCOUNT_ID` | the TikTok id from step 2 |
| `BRAND_HANDLE` | your TikTok handle, e.g. `@yourpokerhandle` (shown on the end card; optional) |

Also check **Settings → Actions → General → Workflow permissions** is set to **Read and write** so the Action can save `state/history.json`.

### 4. Test it
1. Go to the **Actions** tab → **Post to TikTok** → **Run workflow**. Leave **Dry run** checked → Run.
   When it finishes, open the run and download the **video-N** artifact. That's the MP4 plus its caption. Nothing was posted.
2. Run it again with **Dry run unchecked**. This one really posts. Check your TikTok.

From then on it runs on its own twice a day.

### 5. Put your Telegram club in your TikTok bio
Edit your TikTok profile and add your Telegram club link as the bio website. TikTok usually only allows a clickable link once you have 1,000 followers (or on a Business account). Until then, write the Telegram handle in the bio as text, e.g. `Free play-money club: Telegram @yourclub`.

### 6. Music (optional, any time)
Drop `.mp3` or `.wav` beats into `music/` and push. Each video picks one at random and mixes it in at about -18 dB with a 1 s fade in/out. With no files there, videos get a silent audio track. To change the level, add a repository **variable** (not a secret) `MUSIC_GAIN_DB`, e.g. `-12`.

---

## How it handles problems
* **Upload or create-post fails:** retried up to 3 times with backoff. Before retrying a post it checks whether the earlier attempt actually went through, so it never double-posts.
* **Still failing, or TikTok rejects the video:** the Action fails (red ❌) and GitHub emails you. The content is *not* marked as used, so it's retried next run.
* **TikTok still processing after 15 minutes:** recorded as `processing` (never reposted). The next run re-checks it and updates the status.
* **Two runs at once:** prevented by a concurrency group.

## Schedule and time zones
GitHub cron is UTC. `30 17 * * *` and `30 0 * * *` are 12:30 PM and 7:30 PM **Eastern Standard Time**.
During daylight saving time (mid-March to early November) they fire an hour later: 1:30 PM and 8:30 PM.
GitHub sometimes starts scheduled runs a few minutes late. To change times, edit `.github/workflows/post.yml`.

GitHub pauses scheduled workflows in repos with no activity for 60 days. The Action commits `state/history.json` after every post, which normally keeps the repo active. If posting ever stops, check the Actions tab for a "workflow disabled" notice and re-enable it.

---

## Running locally
```bash
pip install -r requirements.txt
```

```bash
python main.py --dry-run
```

```bash
python main.py --dry-run --item q07
```

```bash
python main.py --dry-run --item gen-quiz-00003
```

Output goes to `out/` (`<id>.mp4`, `<id>.txt` caption, `<id>.json` item). Requires `ffmpeg` on your PATH.

```bash
python -m pytest -q
```

The tests brute-force check every generator's math, the hand evaluator, every library item's cards, the rotation rules and the caption rules.

## Project layout
```
main.py                 pick -> render -> upload -> post -> record
content/library.json    your starter library (14 breakdowns + 14 quizzes)
content/generators.py   unlimited verified quizzes/breakdowns
content/cards.py        card notation + hand evaluator
content/equity.py       outs, equity (exact + Monte Carlo), pot odds
content/rotation.py     alternating formats, library first, never repeat, history.json
render/                 Pillow drawing + timeline animation + ffmpeg encoding
publish/postforme.py    Post for Me API client (upload, post, poll results)
publish/captions.py     caption + CTA + hashtags (no links, compliance-checked)
scripts/list_accounts.py  print your Post for Me account ids
state/history.json      everything that has been posted (+ its TikTok metrics)
state/performance.md    auto-updated report: what's working
content/learning.py     metrics sync, club-intent score, Thompson-sampling choices
music/                  drop beats here
assets/fonts/           Poppins (OFL) + DejaVu Sans (suit symbols)
```

## Post for Me API reference used
Endpoints and field names come from the official `post-for-me` SDK (generated from the API's OpenAPI spec):
`POST /v1/media/create-upload-url` → `{upload_url, media_url}`, then `PUT` the file to `upload_url`;
`POST /v1/social-posts` with `caption`, `social_accounts`, `media[{url}]`, `external_id` and
`platform_configurations.tiktok` (`privacy_status: "public"`, `allow_comment`, `allow_duet`, `allow_stitch`: true;
`is_ai_generated`, `disclose_your_brand`, `disclose_branded_content`, `is_draft`: false);
`GET /v1/social-post-results?post_id=…` for the TikTok outcome; `GET /v1/social-accounts` for account ids.
Auth: `Authorization: Bearer <API key>`.
