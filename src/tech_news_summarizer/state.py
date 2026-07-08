"""Dedup state: which issue date was last sent per newsletter category."""

import datetime as dt
import json
import os
import tempfile
from pathlib import Path


def load_state(path: Path) -> dict[str, str]:
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def already_sent(state: dict[str, str], category: str, date: dt.date) -> bool:
    return state.get(category) == date.isoformat()


def mark_sent(state: dict[str, str], category: str, date: dt.date) -> None:
    state[category] = date.isoformat()


def save_state(state: dict[str, str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
