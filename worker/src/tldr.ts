// Fetch and parse TLDR newsletter issues (TypeScript port of the Python
// fetcher's essentials — see src/tech_news_summarizer/fetcher.py).

export interface Story {
  category: string;
  headline: string;
  blurb: string;
  url: string | null;
}

export interface DayStories {
  date: string; // the most recent issue date included
  stories: Story[];
  categories: string[];
}

// Keep in sync with src/tech_news_summarizer/config.py. Cadence varies, so
// not every slug publishes daily — fetchIssue returns null for missing days.
export const CATEGORIES = ["tech", "ai", "it", "dev", "infosec", "devops", "design", "data"];
export const CATEGORY_NAMES: Record<string, string> = {
  tech: "Tech",
  ai: "AI",
  it: "IT",
  dev: "Web Dev",
  infosec: "InfoSec",
  devops: "DevOps",
  design: "Design",
  data: "Data",
};

const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36";
const CACHE_TTL_SECONDS = 6 * 3600;

function decodeEntities(text: string): string {
  return text
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(parseInt(dec, 10)))
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&nbsp;", " ");
}

function stripTags(html: string): string {
  return decodeEntities(html.replace(/<[^>]*>/g, " "))
    .replace(/\s+/g, " ")
    .trim();
}

function cleanUrl(raw: string): string | null {
  try {
    const url = new URL(decodeEntities(raw));
    for (const key of [...url.searchParams.keys()]) {
      if (key.toLowerCase().startsWith("utm_")) url.searchParams.delete(key);
    }
    return url.toString();
  } catch {
    return null;
  }
}

function parseStories(html: string, category: string): Story[] {
  const stories: Story[] = [];
  for (const articleMatch of html.matchAll(/<article[^>]*>([\s\S]*?)<\/article>/g)) {
    const article = articleMatch[1];
    const h3 = article.match(/<h3[^>]*>([\s\S]*?)<\/h3>/);
    if (!h3) continue;
    const headline = stripTags(h3[1]);

    const href = article.match(/<a[^>]*href="([^"]+)"/)?.[1] ?? null;
    // Skip sponsored stories and TLDR self-promotion (mailto: links).
    if (headline.toLowerCase().includes("(sponsor)") || href?.startsWith("mailto:")) continue;

    const blurbMatch = article.match(/<div[^>]*class="[^"]*newsletter-html[^"]*"[^>]*>([\s\S]*?)<\/div>/);
    const blurb = blurbMatch ? stripTags(blurbMatch[1]) : stripTags(article.replace(h3[0], ""));

    const url = href && href.startsWith("http") ? cleanUrl(href) : null;
    stories.push({ category, headline, blurb, url });
  }
  return stories;
}

async function fetchIssue(category: string, date: string): Promise<Story[] | null> {
  const resp = await fetch(`https://tldr.tech/${category}/${date}`, {
    headers: { "user-agent": UA },
  });
  if (resp.status === 404) return null;
  if (!resp.ok) throw new Error(`tldr.tech ${category}/${date} returned ${resp.status}`);
  const stories = parseStories(await resp.text(), category);
  // Unpublished dates serve the signup landing page (no <article> stories).
  return stories.length > 0 ? stories : null;
}

/** Latest available stories across all newsletters (today, falling back to yesterday). */
export async function latestStories(kv: KVNamespace): Promise<DayStories | null> {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);

  const cacheKey = `stories:v1:${today}`;
  const cached = await kv.get<DayStories>(cacheKey, "json");
  if (cached) return cached;

  const results = await Promise.all(
    CATEGORIES.map(async (category) => {
      for (const date of [today, yesterday]) {
        const parsed = await fetchIssue(category, date).catch(() => null);
        if (parsed) return { category, date, parsed };
      }
      return null;
    })
  );

  const stories: Story[] = [];
  const categories: string[] = [];
  let newestDate = "";
  for (const r of results) {
    if (!r) continue;
    stories.push(...r.parsed);
    categories.push(r.category);
    if (r.date > newestDate) newestDate = r.date;
  }
  if (stories.length === 0) return null;

  const result: DayStories = { date: newestDate, stories, categories };
  await kv.put(cacheKey, JSON.stringify(result), { expirationTtl: CACHE_TTL_SECONDS });
  return result;
}
