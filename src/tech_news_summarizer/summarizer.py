"""Merge parsed newsletters into one deduplicated digest via the opencode API.

Takes the already-parsed stories (headline + blurb + url) from every fetched
newsletter and asks an LLM to deduplicate cross-newsletter coverage, pick the
most significant stories overall, and group them into themed sections. Returns
the same Issue shape so the Telegram formatter needs no special handling;
callers fall back to per-newsletter parsed digests when this fails.
"""

import json
import re

import requests

from .fetcher import Issue, Section, Story

DEFAULT_MODEL = "deepseek-v4-flash"

SYSTEM_PROMPT = """\
You merge several TLDR newsletters from the same day into one digest for a \
reader who follows software engineering, AI, security, IT, data, and design \
news with equal interest — significance is judged within each field, not \
against the others.

The user message contains stories as a JSON list of \
{"category", "headline", "blurb", "url"} objects, drawn from multiple \
newsletters. Big stories often appear in more than one newsletter — treat \
those as ONE story (keep the best url). Select the 10-15 most significant \
stories overall and group them into 2-4 themed sections with short section \
names (e.g. "AI & Models", "Security", "Dev Tools"). For each story write a \
short punchy headline and a single-sentence summary of what happened and why \
it matters. Copy the story's "url" value verbatim from the input — never \
invent or modify URLs.

Respond with ONLY a JSON object, no prose and no markdown fences:
{"sections": [{"name": "...", "points": [{"headline": "...", "summary": "...", "url": "..."}]}]}\
"""


class SummarizeError(Exception):
    pass


def summarize_combined(
    api_url: str, api_key: str, model: str, issues: list[tuple[str, Issue]]
) -> Issue:
    """Condense (category, Issue) pairs into a single themed Issue."""
    stories = [
        {"category": category, "headline": s.headline, "blurb": s.blurb, "url": s.url}
        for category, issue in issues
        for section in issue.sections
        for s in section.stories
    ]
    payload = json.dumps(stories, ensure_ascii=False)

    try:
        resp = requests.post(
            api_url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Today's TLDR newsletter stories:\n{payload}"},
                ],
            },
            timeout=120,
        )
    except requests.RequestException as e:
        raise SummarizeError(f"opencode request failed: {e}") from e
    if resp.status_code != 200:
        raise SummarizeError(f"opencode returned {resp.status_code}: {resp.text[:300]}")

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as e:
        raise SummarizeError(f"unexpected opencode response shape: {e}") from e

    valid_urls = {s["url"] for s in stories if s["url"]}
    return Issue(tagline="", sections=_parse_sections(content, valid_urls))


def _parse_sections(content: str, valid_urls: set[str]) -> list[Section]:
    """Parse the model's JSON, tolerating markdown fences; validate defensively."""
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise SummarizeError(f"model did not return valid JSON: {e}") from e

    raw_sections = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(raw_sections, list) or not raw_sections:
        raise SummarizeError("model JSON is missing a non-empty 'sections' list")

    sections: list[Section] = []
    for raw in raw_sections:
        if not isinstance(raw, dict) or not isinstance(raw.get("points"), list):
            continue
        name = raw.get("name")
        stories = _parse_points(raw["points"], valid_urls)
        if stories:
            sections.append(Section(name=name if isinstance(name, str) else "", stories=stories))

    if not any(s.stories for s in sections):
        raise SummarizeError("model JSON contained no usable points")
    return sections


def _parse_points(raw_points: list, valid_urls: set[str]) -> list[Story]:
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
    return points
