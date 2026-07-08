"""Condense a parsed issue into key points via the opencode Zen API.

Takes the already-parsed stories (headline + blurb + url) and asks an LLM to
pick the 5-8 most significant ones. Returns the same Issue shape so the
Telegram formatter needs no special handling; callers fall back to the full
parsed issue when this fails.
"""

import json
import re

import requests

from .fetcher import Issue, Section, Story

DEFAULT_MODEL = "deepseek-v4-flash"
KEY_POINTS_SECTION = "🔑 Key points"

SYSTEM_PROMPT = """\
You condense a tech newsletter into its key points for a software engineer.

The user message contains the newsletter's stories as a JSON list of \
{"headline", "blurb", "url"} objects. Pick the 5-8 most significant stories. \
For each, write a short punchy headline and a single-sentence summary of what \
happened and why it matters. Copy the story's "url" value verbatim from the \
input — never invent or modify URLs.

Respond with ONLY a JSON object, no prose and no markdown fences:
{"points": [{"headline": "...", "summary": "...", "url": "..."}]}\
"""


class SummarizeError(Exception):
    pass


def summarize(api_url: str, api_key: str, model: str, category: str, issue: Issue) -> Issue:
    stories = [s for section in issue.sections for s in section.stories]
    payload = json.dumps(
        [{"headline": s.headline, "blurb": s.blurb, "url": s.url} for s in stories],
        ensure_ascii=False,
    )

    try:
        resp = requests.post(
            api_url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"TLDR {category} newsletter stories:\n{payload}"},
                ],
            },
            timeout=120,
        )
    except requests.RequestException as e:
        raise SummarizeError(f"opencode Zen request failed: {e}") from e
    if resp.status_code != 200:
        raise SummarizeError(f"opencode Zen returned {resp.status_code}: {resp.text[:300]}")

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as e:
        raise SummarizeError(f"unexpected opencode Zen response shape: {e}") from e

    valid_urls = {s.url for s in stories if s.url}
    points = _parse_points(content, valid_urls)
    return Issue(
        tagline=issue.tagline,
        sections=[Section(name=KEY_POINTS_SECTION, stories=points)],
    )


def _parse_points(content: str, valid_urls: set[str]) -> list[Story]:
    """Parse the model's JSON, tolerating markdown fences; validate defensively."""
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise SummarizeError(f"model did not return valid JSON: {e}") from e

    raw_points = data.get("points") if isinstance(data, dict) else None
    if not isinstance(raw_points, list) or not raw_points:
        raise SummarizeError("model JSON is missing a non-empty 'points' list")

    points: list[Story] = []
    for p in raw_points:
        if not isinstance(p, dict):
            continue
        headline, summary = p.get("headline"), p.get("summary")
        if not (isinstance(headline, str) and headline and isinstance(summary, str) and summary):
            continue
        # Hallucination guard: only keep URLs that exist in the input stories.
        url = p.get("url")
        if url not in valid_urls:
            url = None
        points.append(Story(headline=headline, blurb=summary, url=url))

    if not points:
        raise SummarizeError("model JSON contained no usable points")
    return points
