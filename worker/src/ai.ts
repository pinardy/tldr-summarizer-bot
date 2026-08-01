// OpenAI-compatible LLM API client (mirrors src/tech_news_summarizer/summarizer.py).
// Defaults to Gemini's compatibility endpoint — OPENCODE_API_KEY (name is
// historical) then holds a Gemini API key. Override the endpoint/model with
// the optional OPENCODE_API_URL / OPENCODE_MODEL vars (wrangler.toml [vars]
// or `wrangler secret put`).

export interface Env {
  STORE: KVNamespace;
  TELEGRAM_BOT_TOKEN: string;
  OPENCODE_API_KEY: string;
  OPENCODE_API_URL?: string;
  OPENCODE_MODEL?: string;
  WEBHOOK_SECRET: string;
  ALLOWED_CHAT_ID: string;
}

const DEFAULT_API_URL =
  "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions";
const DEFAULT_MODEL = "gemini-3.5-flash";

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export async function chat(env: Env, messages: ChatMessage[]): Promise<string> {
  const resp = await fetch(env.OPENCODE_API_URL || DEFAULT_API_URL, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.OPENCODE_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({ model: env.OPENCODE_MODEL || DEFAULT_MODEL, messages }),
  });
  if (!resp.ok) {
    throw new Error(`LLM API returned ${resp.status}: ${(await resp.text()).slice(0, 300)}`);
  }
  const data = (await resp.json()) as { choices?: { message?: { content?: string } }[] };
  const content = data.choices?.[0]?.message?.content;
  if (!content) throw new Error("unexpected LLM API response shape");
  return content;
}

/** Parse a JSON payload from model output, tolerating markdown fences. */
export function parseModelJson(content: string): unknown {
  let text = content.trim();
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)\s*```/);
  if (fenced) text = fenced[1];
  return JSON.parse(text);
}
