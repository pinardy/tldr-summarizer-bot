"""Fetch TLDR newsletter issues and parse them into structured stories.

TLDR issues are already curated summaries — each story on the page is a
headline + short blurb + link — so no LLM is needed; we parse the page
structure directly.
"""

import datetime as dt
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://tldr.tech"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}


class FetchError(Exception):
    pass


@dataclass
class Story:
    headline: str      # includes TLDR's "(N minute read)" tag
    blurb: str         # TLDR's own summary, verbatim
    url: str | None


@dataclass
class Section:
    name: str
    stories: list[Story] = field(default_factory=list)


@dataclass
class Issue:
    tagline: str
    sections: list[Section]


def fetch_issue(category: str, date: dt.date) -> Issue | None:
    """Return the parsed issue, or None if not published.

    Unpublished dates (weekends/holidays) serve the newsletter's signup
    landing page with HTTP 200 — it contains no story <article> elements,
    so "zero stories parsed" means "not published".
    """
    url = f"{BASE_URL}/{category}/{date:%Y-%m-%d}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise FetchError(f"GET {url} returned {resp.status_code}")
    issue = _parse_issue(resp.text)
    if not any(section.stories for section in issue.sections):
        return None
    return issue


def _parse_issue(html: str) -> Issue:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("main") or soup.body or soup

    h2 = root.find("h2")
    tagline = h2.get_text(" ", strip=True) if h2 else ""

    sections: list[Section] = [Section(name="")]
    # Walk in document order: bold centered <h3>s outside articles start a new
    # section; each <article> is a story in the current section.
    for el in root.find_all(["h3", "article"]):
        if el.name == "h3":
            if el.find_parent("article") is None and el.get_text(strip=True):
                sections.append(Section(name=el.get_text(" ", strip=True)))
            continue
        story = _parse_story(el)
        if story is not None:
            sections[-1].stories.append(story)

    return Issue(tagline=tagline, sections=[s for s in sections if s.stories])


def _parse_story(article) -> Story | None:
    h3 = article.find("h3")
    if h3 is None:
        return None
    headline = h3.get_text(" ", strip=True)

    a = article.find("a", href=True)
    href = a["href"] if a else None

    # Skip sponsored stories and TLDR self-promotion (mailto: links).
    if "(sponsor)" in headline.lower() or (href and href.startswith("mailto:")):
        return None

    blurb_div = article.find("div", class_="newsletter-html")
    if blurb_div is not None:
        blurb = blurb_div.get_text(" ", strip=True)
    else:
        h3.extract()
        blurb = article.get_text(" ", strip=True)

    url = _clean_url(href) if href and href.startswith("http") else None
    return Story(headline=headline, blurb=blurb, url=url)


def _clean_url(url: str) -> str:
    """Drop utm_* tracking parameters."""
    parts = urlsplit(url)
    params = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")]
    return urlunsplit(parts._replace(query=urlencode(params)))
