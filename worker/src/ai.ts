// opencode Go API client (mirrors src/tech_news_summarizer/summarizer.py).

export interface Env {
  STORE: KVNamespace;
  TELEGRAM_BOT_TOKEN: string;
  OPENCODE_API_KEY: string;
  WEBHOOK_SECRET: string;
  ALLOWED_CHAT_ID: string;
}

const API_URL = "https://opencode.ai/zen/go/v1/chat/completions";
const MODEL = "deepseek-v4-flash";

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export async function chat(env: Env, messages: ChatMessage[]): Promise<string> {
  const resp = await fetch(API_URL, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.OPENCODE_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({ model: MODEL, messages }),
  });
  if (!resp.ok) {
    throw new Error(`opencode returned ${resp.status}: ${(await resp.text()).slice(0, 300)}`);
  }
  const data = (await resp.json()) as { choices?: { message?: { content?: string } }[] };
  const content = data.choices?.[0]?.message?.content;
  if (!content) throw new Error("unexpected opencode response shape");
  return content;
}

/** Parse a JSON payload from model output, tolerating markdown fences. */
export function parseModelJson(content: string): unknown {
  let text = content.trim();
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)\s*```/);
  if (fenced) text = fenced[1];
  return JSON.parse(text);
}
