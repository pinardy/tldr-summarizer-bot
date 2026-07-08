"""Orchestration: fetch and parse each newsletter, publish, record state."""

import argparse
import datetime as dt
import logging
import sys

from . import fetcher, state, summarizer, telegram
from .config import CATEGORIES, load_settings

log = logging.getLogger("tech_news_summarizer")


def run(
    date: dt.date | None = None,
    dry_run: bool = False,
    categories: list[str] | None = None,
    ignore_state: bool = False,
    no_ai: bool = False,
) -> int:
    # TLDR publishes around 6 AM US Eastern, so in timezones ahead of the US
    # "today's" issue often doesn't exist yet at run time. Without an explicit
    # date, fall back to yesterday's issue — the dedup state ensures each
    # issue is still only ever sent once.
    if date is None:
        candidate_dates = [dt.date.today(), dt.date.today() - dt.timedelta(days=1)]
    else:
        candidate_dates = [date]
    categories = categories or list(CATEGORIES)
    settings = load_settings(require_telegram=not dry_run)

    run_state = state.load_state(settings.state_path)
    successes: list[str] = []
    failures: list[str] = []

    for category in categories:
        try:
            issue = None
            for date in candidate_dates:
                if not ignore_state and state.already_sent(run_state, category, date):
                    log.info("%s: skip (already sent for %s)", category, date)
                    break
                issue = fetcher.fetch_issue(category, date)
                if issue is not None:
                    break
                log.info("%s: no issue published for %s", category, date)
            if issue is None:
                continue

            n_stories = sum(len(s.stories) for s in issue.sections)
            log.info("%s: parsed %d stories for %s", category, n_stories, date)

            if settings.opencode_api_key and not no_ai:
                try:
                    issue = summarizer.summarize(
                        settings.opencode_api_url,
                        settings.opencode_api_key,
                        settings.opencode_model,
                        category,
                        issue,
                    )
                    n_points = sum(len(s.stories) for s in issue.sections)
                    log.info("%s: condensed to %d key points", category, n_points)
                except Exception:
                    log.warning(
                        "%s: AI summarization failed, sending full parsed digest",
                        category,
                        exc_info=True,
                    )

            message = telegram.format_digest(category, date, issue)

            if dry_run:
                print(f"\n===== {category} ({date}) =====\n{message}\n")
            else:
                telegram.send_message(
                    settings.telegram_bot_token, settings.telegram_chat_id, message
                )
                state.mark_sent(run_state, category, date)
                state.save_state(run_state, settings.state_path)
                log.info("%s: sent to Telegram", category)
            successes.append(category)
        except Exception:
            log.exception("%s: failed", category)
            failures.append(category)

    if failures and not successes:
        log.error("all attempted newsletters failed: %s", ", ".join(failures))
        if not dry_run:
            try:
                telegram.send_message(
                    settings.telegram_bot_token,
                    settings.telegram_chat_id,
                    f"⚠️ tech-news-summarizer: all newsletters failed today "
                    f"({', '.join(failures)}) — check data/run.log",
                )
            except Exception:
                log.exception("failed to send failure notice")
        return 1
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="Parse TLDR newsletters and post digests to Telegram."
    )
    parser.add_argument("--dry-run", action="store_true", help="print digests instead of sending")
    parser.add_argument(
        "--date",
        type=dt.date.fromisoformat,
        help="issue date (default: today, falling back to yesterday if not yet published)",
    )
    parser.add_argument(
        "--categories",
        type=lambda s: s.split(","),
        help=f"comma-separated subset of: {','.join(CATEGORIES)}",
    )
    parser.add_argument(
        "--ignore-state", action="store_true", help="re-send even if already sent"
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="skip AI key-points summarization and send the full parsed digest",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout
    )
    sys.exit(
        run(
            date=args.date,
            dry_run=args.dry_run,
            categories=args.categories,
            ignore_state=args.ignore_state,
            no_ai=args.no_ai,
        )
    )
