"""Configuration and secrets loading."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# TLDR newsletter URL slugs (https://tldr.tech/<category>/<YYYY-MM-DD>).
# Note: Web Dev lives at "dev" — "webdev" is a redirect.
CATEGORIES = ["tech", "ai", "dev", "infosec", "devops", "design"]

# Human-readable names for Telegram headers.
CATEGORY_NAMES = {
    "tech": "Tech",
    "ai": "AI",
    "dev": "Web Dev",
    "infosec": "InfoSec",
    "devops": "DevOps",
    "design": "Design",
}


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: str
    opencode_api_key: str = ""  # optional — empty means no AI summarization
    # Default endpoint is the opencode Go subscription; pay-as-you-go Zen is
    # https://opencode.ai/zen/v1/chat/completions (set OPENCODE_API_URL).
    opencode_api_url: str = "https://opencode.ai/zen/go/v1/chat/completions"
    opencode_model: str = "deepseek-v4-flash"
    state_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "state.json")
    categories: tuple[str, ...] = tuple(CATEGORIES)


def load_settings(require_telegram: bool = True) -> Settings:
    """Load .env (explicit path — launchd's cwd is not the project) and validate.

    Telegram credentials are only needed when actually sending, so dry runs
    pass require_telegram=False.
    """
    load_dotenv(PROJECT_ROOT / ".env")

    missing = [
        name
        for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
        if not os.environ.get(name)
    ]
    if require_telegram and missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            f"Copy .env.example to {PROJECT_ROOT / '.env'} and fill them in."
        )

    return Settings(
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        opencode_api_key=os.environ.get("OPENCODE_API_KEY", ""),
        opencode_api_url=os.environ.get(
            "OPENCODE_API_URL", "https://opencode.ai/zen/go/v1/chat/completions"
        ),
        opencode_model=os.environ.get("OPENCODE_MODEL", "deepseek-v4-flash"),
    )
