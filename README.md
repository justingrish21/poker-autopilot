# Poker TikTok Autopilot

Fully automatic poker strategy videos for TikTok. Every day at about 12:30 PM and 7:30 PM (Detroit time) a GitHub Action:

1. picks the next piece of content (it alternates hand breakdowns and quizzes, never repeats),
2. renders a 1080x1920 MP4 entirely with code (Python + Pillow + ffmpeg, no AI or paid tools),
3. uploads it to your TikTok through the [Post for Me](https://api.postforme.dev) API,
4. posts the same video to **Instagram** (@poke.rpilot) as a Reel shared to the feed, with the same caption,
5. waits until both platforms confirm, and records each result in `state/history.json`.

Instagram uses Post for Me account `spc_kjp4NbyL89rCNXnxcjnkW` by default (set in `.github/workflows/post.yml`).
To use a different Instagram account, add a `PFM_INSTAGRAM_ACCOUNT_ID` secret; set it to `none` to post to TikTok only.
If Instagram rejects a video but TikTok accepts it, the run fails (so GitHub emails you) but the video counts as posted.

Every video ends with: **"Want to play? Play for chips with the link in my bio"**, your @handle, and "Practice these spots with real players."

It costs nothing to run besides your Post for Me plan. GitHub Actions is free for this.

---

## What the videos look like

| Format | Length | Flow |
|---|---|---|
| **Hand breakdown** | 22 s | hook → table, cards slide/flip in → "What's the play?" → **THE PLAY** banner (flash + chip confetti) → 3 reasons → end card |
| **Quiz** | 18 s | hook → question, cards, A/B/C answers → 3-2-1 "Comment your answer" → correct answer glows green (flash + confetti), explanation → end card |
| **All-in story** | 22-24 s | looks like a hand in a mobile poker app: PokerPilot vs randomly named players, cards dealt, betting, all in, live equity %, the board runs out, the river sweat → end card. Three kinds: **bad beat** (PokerPilot loses as a big favorite), **suckout** (PokerPilot hits a miracle river), **cooler** (set over set and friends; PokerPilot ships it). Every % and out count is computed. |

* Dark background, green felt table, real-looking cards, big outlined text.
* Everything important stays inside TikTok's safe zone: nothing in the top 150 px, the bottom 350 px or the right 140 px.
* Built for engagement: punchy hooks, "comment your answer" prompts, a countdown and reveal effects.
* Never mentions real money, deposits, rakeback or payouts, in the video or the caption. Every item and caption runs through a compliance check before posting, so the account reads as a poker strategy/education page.

## Content never runs out

* **Daily plan:** every day posts **one quiz and one all-in story**. The first post of the Detroit day is the quiz,
  the second is the all-in story (checked against what was already posted today, so late or failed runs never double up).
  Hand breakdowns are still available manually: Actions → Post to TikTok → Run workflow → format `breakdown`.
* `content/library.json` holds your 14 breakdowns and 14 quizzes. They're used first, in order.
* After that, `content/generators.py` creates unlimited new, mathematically verified content:
  pot odds, outs (counted by enumerating the deck), Rule of 2 and 4 (with the exact %),
  preflop equity (20,000-runout Monte Carlo), combo/blocker counting, and "call or fold this draw?"
  breakdowns (exact equity vs. a real villain hand, compared against the real pot odds).
* `state/history.json` records every post (id, content hash, time, Post for Me post id, status, TikTok URL).
  The same content is never posted twice.

## It learns what makes people want to play

The goal is club sign-ups, so every run:

1. **Pulls TikTok and Instagram results** for past videos from Post for Me (views, likes, comments, shares;
   with a TikTok **Business** account also profile views, new followers and link clicks).
2. **Scores each video for "club intent"** once it's 48 hours old:
   `0.02 x views + likes + 4 x comments + 6 x shares + 3 x saves + 5 x profile views + 15 x follows + 25 x link clicks`.
   Signals that mean "I want more / I want in" count far more than passive views.
3. **Adjusts automatically** using Thompson sampling (a standard "test and shift" method). After 6 judged
   videos it starts favoring what scores best while still testing alternatives:
   * **Content type:** pot odds, outs, equity, combos, call-or-fold draws, and bad beat vs suckout vs cooler.
   * **Hook tag** on the opening screen ("POKER QUIZ", "WHAT WOULD YOU DO?"...).
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

### 5. Put your link-in-bio page in your TikTok bio
The page in `linktree/` sends viewers to the club (ClubGG invite link). Build it with
`cd linktree && npm ci && npm run build`, then upload the `dist/` folder to Netlify Drop
(app.netlify.com/drop) and put the resulting `https://<name>.netlify.app` address in the
TikTok bio's website field. Until TikTok allows a clickable link (usually 1,000 followers or
a Business account), write "Free poker club: link on my profile soon" or similar as text.

### 6. Sound (automatic) and your beats (optional, any time)
Every video has sound: effects synced to the action (card flips, chip clinks, whooshes, countdown ticks,
a ding on the right answer, an impact on reveals, a heartbeat during the river sweat, a win or bad-beat sting)
over an original beat generated in code. Everything is synthesized, so no samples and no licensing issues.
Drop your own `.mp3`/`.wav` beats into `music/` and they replace the generated beat (mixed at about -18 dB under
the effects). The final mix is loudness-matched to about -15 LUFS. Set the `MUSIC_GAIN_DB` repo variable to change the beat level.

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
content/allin.py        all-in stories: bad beats, suckouts, coolers (verified odds)
render/allin.py         the poker-app style table for all-in stories
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
