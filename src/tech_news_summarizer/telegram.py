"""Format parsed issues as Telegram HTML and send them via the Bot API."""

import datetime as dt
import html

import requests

from .config import CATEGORY_NAMES
from .fetcher import Issue

TELEGRAM_LIMIT = 4096


class TelegramError(Exception):
    pass


def format_digest(category: str, date: dt.date, issue: Issue) -> str:
    """Per-newsletter digest (fallback path when AI merging is unavailable)."""
    name = CATEGORY_NAMES.get(category, category)
    lines = [f"<b>📰 TLDR {html.escape(name)} — {date.isoformat()}</b>"]
    if issue.tagline:
        lines.append(f"<i>{html.escape(issue.tagline)}</i>")
    lines.append("")
    lines.extend(_format_issue_body(issue))
    return "\n".join(lines).strip()


def format_combined_digest(date: dt.date, categories: list[str], issue: Issue) -> str:
    """Single merged digest across all fetched newsletters."""
    names = ", ".join(CATEGORY_NAMES.get(c, c) for c in categories)
    lines = [
        f"<b>📰 TLDR Daily Digest — {date.isoformat()}</b>",
        f"<i>{html.escape(names)}</i>",
        "",
    ]
    lines.extend(_format_issue_body(issue))
    return "\n".join(lines).strip()


def _format_issue_body(issue: Issue) -> list[str]:
    lines: list[str] = []
    for section in issue.sections:
        if section.name:
            lines.append(f"<b><u>{html.escape(section.name)}</u></b>")
        for story in section.stories:
            headline = html.escape(story.headline)
            if story.url:
                lines.append(
                    f'• <a href="{html.escape(story.url, quote=True)}"><b>{headline}</b></a>'
                )
            else:
                lines.append(f"• <b>{headline}</b>")
            lines.append(f"  {html.escape(story.blurb)}")
            lines.append("")
    return lines


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > limit and current:
            chunks.append(current)
            current = para
        else:
            current = candidate
    if current:
        chunks.append(current)
    # A single paragraph longer than the limit is still possible in theory.
    return [c[i : i + limit] for c in chunks for i in range(0, len(c), limit)]


def send_message(token: str, chat_id: str, html_text: str) -> None:
    for chunk in split_message(html_text):
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if not payload.get("ok"):
            raise TelegramError(f"sendMessage failed ({resp.status_code}): {resp.text[:300]}")
