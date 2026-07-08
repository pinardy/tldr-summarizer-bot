# tech-news-summarizer

Daily digest of [TLDR](https://tldr.tech) newsletters: fetches the latest issues,
parses out the stories (headline, blurb, link — sponsors filtered out), and posts
them to your Telegram. Completely free to run: no LLM API involved, and the
Telegram Bot API costs nothing.

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
  (copy it from the Zen console) enables AI key-points mode: each newsletter
  is condensed to the 5–8 most important stories. The default endpoint and
  model target the **opencode Go subscription** (`deepseek-v4-flash` at
  `…/zen/go/v1/chat/completions`); pay-as-you-go Zen users set
  `OPENCODE_API_URL=https://opencode.ai/zen/v1/chat/completions`. Without a
  key — or if the AI call fails — the full parsed story list is sent instead,
  so delivery never depends on the AI. Force the full list with `--no-ai`.

### 2. Test

```bash
# Print digests to the terminal without sending anything
uv run python -m tech_news_summarizer --dry-run --date 2026-07-07

# Send a single newsletter to Telegram
uv run python -m tech_news_summarizer --categories ai

# Re-running is a no-op (dedup via data/state.json); force with --ignore-state
uv run python -m tech_news_summarizer --categories ai
```

### 3. Schedule via GitHub Actions (primary)

The repo ships a scheduled workflow (`.github/workflows/digest.yml`) that runs
daily at 01:00 UTC (09:00 SGT) on GitHub's free tier — no machine of yours
needs to be awake.

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
- TLDR publishes around 6 AM US Eastern, so the 01:00 UTC run picks up
  **yesterday's** issue automatically when today's isn't out yet; the state
  file makes reruns idempotent (a category is only ever sent once per issue
  date).

### Alternative: run locally via launchd (macOS)

```bash
cp launchd/com.pinardy.tech-news-summarizer.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.pinardy.tech-news-summarizer.plist
# remove: launchctl bootout gui/$(id -u)/com.pinardy.tech-news-summarizer
```

Don't run both schedulers at once — the shared state file lives in two places
(laptop vs repo), so double sends can occur.

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
                             →  summarizer.py (optional: condense to 5-8 key
                                               points via opencode Zen; falls
                                               back to the full list on failure)
                             →  telegram.py   (HTML message per newsletter,
                                               split at 4096 chars)
                             →  state.py      (data/state.json dedup)
```

- TLDR issues are already curated summaries, so the digest reuses TLDR's own
  blurbs verbatim — no AI required.
- A failing category never blocks the others.
- If every attempted category fails, a warning message is sent to Telegram and
  the run exits non-zero.
- Logs land in `data/run.log` when run via launchd.
