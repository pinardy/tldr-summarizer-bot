"""Persist sent digests as JSON artifacts for the static archive page.

Artifacts land in docs/data/ (served by GitHub Pages) and are committed back
to the repo by the scheduled workflow, alongside the dedup state.
"""

import dataclasses
import datetime as dt
import json
from pathlib import Path

from .config import CATEGORY_NAMES, PROJECT_ROOT
from .fetcher import Issue

ARCHIVE_DIR = PROJECT_ROOT / "docs" / "data"


def save_combined(
    date: dt.date, categories: list[str], merged: Issue, archive_dir: Path = ARCHIVE_DIR
) -> None:
    names = ", ".join(CATEGORY_NAMES.get(c, c) for c in categories)
    _save(
        date,
        "combined",
        categories,
        [
            {
                "title": "TLDR Daily Digest",
                "tagline": merged.tagline or names,
                "sections": [dataclasses.asdict(s) for s in merged.sections],
            }
        ],
        archive_dir,
    )


def save_per_newsletter(
    date: dt.date,
    sent: list[tuple[str, dt.date, Issue]],
    archive_dir: Path = ARCHIVE_DIR,
) -> None:
    _save(
        date,
        "per-newsletter",
        [category for category, _, _ in sent],
        [
            {
                "title": f"TLDR {CATEGORY_NAMES.get(category, category)} — {issue_date.isoformat()}",
                "tagline": issue.tagline,
                "sections": [dataclasses.asdict(s) for s in issue.sections],
            }
            for category, issue_date, issue in sent
        ],
        archive_dir,
    )


def _save(
    date: dt.date,
    mode: str,
    categories: list[str],
    digests: list[dict],
    archive_dir: Path,
) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    artifact = {
        "date": date.isoformat(),
        "mode": mode,
        "categories": categories,
        "digests": digests,
    }
    with open(archive_dir / f"{date.isoformat()}.json", "w") as f:
        json.dump(artifact, f, ensure_ascii=False, indent=2)

    dates = sorted(
        (p.stem for p in archive_dir.glob("????-??-??.json")),
        reverse=True,
    )
    with open(archive_dir / "index.json", "w") as f:
        json.dump(dates, f, indent=2)
