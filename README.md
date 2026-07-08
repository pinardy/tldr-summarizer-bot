# tech-news-summarizer

Daily digest of [TLDR](https://tldr.tech) newsletters: fetches the latest issues,
parses out the stories (headline, blurb, link — sponsors filtered out), merges
them into **one deduplicated, themed digest** via the opencode API, and posts
it to your Telegram. Runs twice daily on GitHub Actions' free tier.

Covered newsletters: **Tech, AI, Web Dev, InfoSec, DevOps, Design**
(TLDR publishes on weekdays; unpublished dates are skipped automatically).

## Setup

Requires [uv](https://docs.astral.sh/uv/). Dependencies install automatically on first `uv run`.

### 1. Credentials

```bash
cp .env.example .env
```

Fill in `.env`:

- `TELEGRAM_BOT_TOKEN` — message [@BotFather](https://t.me/BotFather) on Telegram,
  send `/newbot`, follow the prompts, copy the token
- `TELEGRAM_CHAT_ID` — send any message to your new bot, then open
  `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy
  `result[0].message.chat.id`
- `OPENCODE_API_KEY` *(optional)* — an [opencode](https://opencode.ai) key
  (copy it from the Zen console) enables the merged digest: all newsletters
  are combined into one message, cross-newsletter duplicates removed, the
  10–15 most significant stories grouped into themed sections. The default
  endpoint and model target the **opencode Go subscription**
  (`deepseek-v4-flash` at `…/zen/go/v1/chat/completions`); pay-as-you-go Zen
  users set `OPENCODE_API_URL=https://opencode.ai/zen/v1/chat/completions`.
  Without a key — or if the AI call fails — one full parsed story list is
  sent per newsletter instead, so delivery never depends on the AI. Force
  that mode with `--no-ai`.

### 2. Test

```bash
# Print digests to the terminal without sending anything
uv run python -m tech_news_summarizer --dry-run --date 2026-07-07

# Send a single newsletter to Telegram
uv run python -m tech_news_summarizer --categories ai

# Re-running is a no-op (dedup via data/state.json); force with --ignore-state
uv run python -m tech_news_summarizer --categories ai
```

### 3. Schedule via GitHub Actions

The repo ships a scheduled workflow (`.github/workflows/digest.yml`) that runs
twice daily on GitHub's free tier — no machine of yours needs to be awake:

- **13:00 UTC (21:00 SGT)** — TLDR publishes ~6 AM US Eastern (10–11:00 UTC),
  so this delivers each issue the evening it comes out.
- **01:00 UTC (09:00 SGT)** — catch-up for late publishes or missed runs.

Setup (once):

```bash
gh repo create tldr-summarizer-bot --private --source . --push
gh secret set TELEGRAM_BOT_TOKEN
gh secret set TELEGRAM_CHAT_ID
gh secret set OPENCODE_API_KEY        # optional, enables AI key points

# Fire immediately to test:
gh workflow run digest.yml && gh run watch
```

Notes:

- **State persistence**: Actions runners are ephemeral, so the workflow
  commits `data/state.json` back to the repo after each run. This doubles as
  repo activity, which stops GitHub from auto-disabling the schedule after
  60 days of inactivity.
- Scheduled runs can start 5–15 minutes late during GitHub peak load — fine
  for a news digest.
- The runs are always safe to repeat: each fetch falls back to yesterday's
  issue when today's isn't out yet, and the state file makes everything
  idempotent (a newsletter issue is only ever sent once).

## Talking to the bot

A Cloudflare Worker (`worker/`, free tier) receives your Telegram messages via
webhook and replies in real time — separate from the scheduled push pipeline,
same bot:

- `/digest` — build today's combined digest on demand (cached for 6h)
- `/news <topic>` — today's stories about a topic
- any other message — free-form Q&A with today's stories as context
  (short conversation memory kept for follow-ups)

Only the configured `ALLOWED_CHAT_ID` gets answers; webhook calls are
authenticated with Telegram's `secret_token` header. Slow work (LLM calls)
runs within the request lifetime — `ctx.waitUntil` alone is capped at 30s,
which is shorter than a digest build.

Deploy/update (one-time setup needs `wrangler login`, a KV namespace in
`wrangler.toml`, and four secrets: `TELEGRAM_BOT_TOKEN`, `OPENCODE_API_KEY`,
`WEBHOOK_SECRET`, `ALLOWED_CHAT_ID`):

```bash
cd worker
npm install
npx wrangler deploy
# register the webhook (once):
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -H "content-type: application/json" \
  -d '{"url": "https://tldr-bot.<subdomain>.workers.dev/webhook", "secret_token": "<WEBHOOK_SECRET>", "allowed_updates": ["message"]}'
```

Note: the TLDR parser exists twice (Python for the push pipeline, TypeScript
in `worker/src/tldr.ts`) — keep them in sync if TLDR's HTML changes.

## CLI

```
uv run python -m tech_news_summarizer [--dry-run] [--date YYYY-MM-DD]
                                      [--categories tech,ai,...] [--ignore-state]
                                      [--no-ai]
```

## How it works

```
tldr.tech/{category}/{date}  →  fetcher.py    (parse stories: headline, blurb, link;
                                               sponsors and self-promo filtered,
                                               utm_* tracking params stripped)
                             →  summarizer.py (merge all newsletters into one
                                               digest: dedup cross-newsletter
                                               stories, pick top 10-15, group
                                               into themed sections)
                             →  telegram.py   (one HTML message, split at
                                               4096 chars if needed)
                             →  state.py      (data/state.json dedup)
```

- Fallback chain: AI merge fails → one full parsed digest per newsletter
  (TLDR's own blurbs verbatim). A failing newsletter never blocks the others.
- URLs in the AI digest are validated against the parsed input — the model
  cannot introduce links that weren't in the newsletter.
- If everything fails, a warning message is sent to Telegram and the run
  exits non-zero.
- Run logs are visible in the repo's Actions tab.
