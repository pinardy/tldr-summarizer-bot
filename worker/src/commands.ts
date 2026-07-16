import { chat, ChatMessage, Env, parseModelJson } from "./ai";
import { escapeHtml, sendMessage, sendTyping } from "./telegram";
import { CATEGORY_NAMES, DayStories, latestStories, Story } from "./tldr";

const HELP_TEXT = `<b>TLDR digest bot</b>

/digest — build today's combined digest now
/news &lt;topic&gt; — today's stories about a topic
/help — this message

Or just ask me anything about today's tech news.`;

// Same merging prompt as the Python pipeline (summarizer.py).
const DIGEST_PROMPT = `You merge several TLDR newsletters from the same day into one digest for a \
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
{"sections": [{"name": "...", "points": [{"headline": "...", "summary": "...", "url": "..."}]}]}`;

const QA_PROMPT = `You are a helpful tech-news assistant inside a Telegram bot. The stories below \
are today's TLDR newsletter coverage — use them as your primary source when \
answering. Be concise (a few sentences or a short list). Include a story's \
plain URL when you reference it. Reply in plain text only: no markdown, no \
HTML tags.

Today's stories (JSON):
`;

interface HistoryEntry {
  role: "user" | "assistant";
  content: string;
}

async function getHistory(env: Env, chatId: number): Promise<HistoryEntry[]> {
  return (await env.STORE.get<HistoryEntry[]>(`chat:${chatId}`, "json")) ?? [];
}

async function saveHistory(env: Env, chatId: number, history: HistoryEntry[]): Promise<void> {
  await env.STORE.put(`chat:${chatId}`, JSON.stringify(history.slice(-8)), {
    expirationTtl: 86_400,
  });
}

async function requireStories(env: Env, chatId: number): Promise<DayStories | null> {
  const day = await latestStories(env.STORE);
  if (!day) {
    await sendMessage(
      env.TELEGRAM_BOT_TOKEN,
      chatId,
      "No TLDR issues are available right now (weekend/holiday?). Try again later."
    );
  }
  return day;
}

export async function handleHelp(env: Env, chatId: number): Promise<void> {
  await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId, HELP_TEXT);
}

export async function handleDigest(env: Env, chatId: number): Promise<void> {
  await sendTyping(env.TELEGRAM_BOT_TOKEN, chatId);
  const day = await requireStories(env, chatId);
  if (!day) return;

  // Building the digest costs a slow LLM call — reuse the day's build.
  const cacheKey = `digest:v1:${day.date}`;
  const cached = await env.STORE.get(cacheKey);
  if (cached) {
    await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId, cached);
    return;
  }

  const content = await chat(env, [
    { role: "system", content: DIGEST_PROMPT },
    { role: "user", content: `Today's TLDR newsletter stories:\n${JSON.stringify(day.stories)}` },
  ]);

  const validUrls = new Set(day.stories.map((s) => s.url).filter(Boolean));
  const data = parseModelJson(content) as {
    sections?: { name?: string; points?: { headline?: string; summary?: string; url?: string }[] }[];
  };
  if (!data.sections?.length) throw new Error("model JSON is missing sections");

  const lines = [
    `<b>📰 TLDR Daily Digest — ${day.date}</b>`,
    `<i>${escapeHtml(day.categories.map((c) => CATEGORY_NAMES[c] ?? c).join(", "))}</i>`,
    "",
  ];
  for (const section of data.sections) {
    if (!section.points?.length) continue;
    if (section.name) lines.push(`<b><u>${escapeHtml(section.name)}</u></b>`);
    for (const p of section.points) {
      if (!p.headline || !p.summary) continue;
      const headline = escapeHtml(p.headline);
      // Hallucination guard: only keep URLs that exist in the input stories.
      if (p.url && validUrls.has(p.url)) {
        lines.push(`• <a href="${escapeHtml(p.url)}"><b>${headline}</b></a>`);
      } else {
        lines.push(`• <b>${headline}</b>`);
      }
      lines.push(`  ${escapeHtml(p.summary)}`);
      lines.push("");
    }
  }
  const digest = lines.join("\n").trim();
  await env.STORE.put(cacheKey, digest, { expirationTtl: 6 * 3600 });
  await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId, digest);
}

export async function handleQuestion(env: Env, chatId: number, text: string): Promise<void> {
  await sendTyping(env.TELEGRAM_BOT_TOKEN, chatId);
  const day = await requireStories(env, chatId);
  if (!day) return;

  const history = await getHistory(env, chatId);
  const messages: ChatMessage[] = [
    { role: "system", content: QA_PROMPT + JSON.stringify(day.stories) },
    ...history,
    { role: "user", content: text },
  ];
  const answer = await chat(env, messages);

  await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId, escapeHtml(answer));
  await saveHistory(env, chatId, [
    ...history,
    { role: "user", content: text },
    { role: "assistant", content: answer },
  ]);
}
