"""Orchestration: fetch newsletters, merge into one digest, publish, record state."""

import argparse
import datetime as dt
import logging
import sys

from . import archive, fetcher, state, summarizer, telegram
from .config import CATEGORIES, Settings, load_settings

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

    # Phase 1: fetch every newsletter that has an unsent issue.
    fetched: list[tuple[str, dt.date, fetcher.Issue]] = []
    fetch_failures: list[str] = []
    for category in categories:
        try:
            for cand in candidate_dates:
                if not ignore_state and state.already_sent(run_state, category, cand):
                    log.info("%s: skip (already sent for %s)", category, cand)
                    break
                issue = fetcher.fetch_issue(category, cand)
                if issue is not None:
                    n = sum(len(s.stories) for s in issue.sections)
                    log.info("%s: parsed %d stories for %s", category, n, cand)
                    fetched.append((category, cand, issue))
                    break
                log.info("%s: no issue published for %s", category, cand)
        except Exception:
            log.exception("%s: fetch failed", category)
            fetch_failures.append(category)

    if not fetched:
        if fetch_failures:
            return _report_total_failure(settings, fetch_failures, dry_run)
        log.info("nothing new to send")
        return 0

    # Phase 2: deliver — one merged digest when AI is available, otherwise
    # (or on AI failure) one full parsed digest per newsletter.
    if settings.opencode_api_key and not no_ai:
        try:
            return _deliver_combined(settings, run_state, fetched, dry_run)
        except Exception:
            log.warning(
                "AI merge failed, falling back to per-newsletter digests", exc_info=True
            )
    return _deliver_per_newsletter(settings, run_state, fetched, fetch_failures, dry_run)


def _deliver_combined(
    settings: Settings,
    run_state: dict[str, str],
    fetched: list[tuple[str, dt.date, fetcher.Issue]],
    dry_run: bool,
) -> int:
    merged = summarizer.summarize_combined(
        settings.opencode_api_url,
        settings.opencode_api_key,
        settings.opencode_model,
        [(category, issue) for category, _, issue in fetched],
    )
    n_points = sum(len(s.stories) for s in merged.sections)
    log.info("merged %d newsletters into %d key points", len(fetched), n_points)

    digest_date = max(date for _, date, _ in fetched)
    message = telegram.format_combined_digest(
        digest_date, [category for category, _, _ in fetched], merged
    )

    if dry_run:
        print(f"\n===== combined digest ({digest_date}) =====\n{message}\n")
        return 0

    telegram.send_message(settings.telegram_bot_token, settings.telegram_chat_id, message)
    for category, date, _ in fetched:
        state.mark_sent(run_state, category, date)
    state.save_state(run_state, settings.state_path)
    log.info("combined digest sent to Telegram (%s)", ", ".join(c for c, _, _ in fetched))
    try:
        archive.save_combined(digest_date, [c for c, _, _ in fetched], merged)
    except Exception:
        log.warning("failed to write archive artifact", exc_info=True)
    return 0


def _deliver_per_newsletter(
    settings: Settings,
    run_state: dict[str, str],
    fetched: list[tuple[str, dt.date, fetcher.Issue]],
    fetch_failures: list[str],
    dry_run: bool,
) -> int:
    successes: list[tuple[str, dt.date, fetcher.Issue]] = []
    failures: list[str] = list(fetch_failures)
    for category, date, issue in fetched:
        try:
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
            successes.append((category, date, issue))
        except Exception:
            log.exception("%s: failed", category)
            failures.append(category)

    if successes and not dry_run:
        try:
            archive.save_per_newsletter(max(d for _, d, _ in successes), successes)
        except Exception:
            log.warning("failed to write archive artifact", exc_info=True)

    if failures and not successes:
        return _report_total_failure(settings, failures, dry_run)
    return 0


def _report_total_failure(settings: Settings, failures: list[str], dry_run: bool) -> int:
    log.error("all attempted newsletters failed: %s", ", ".join(failures))
    if not dry_run:
        try:
            telegram.send_message(
                settings.telegram_bot_token,
                settings.telegram_chat_id,
                f"⚠️ tech-news-summarizer: all newsletters failed today "
                f"({', '.join(failures)}) — check the run logs",
            )
        except Exception:
            log.exception("failed to send failure notice")
    return 1


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="Parse TLDR newsletters and post a merged digest to Telegram."
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
        help="skip AI merging and send one full parsed digest per newsletter",
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
