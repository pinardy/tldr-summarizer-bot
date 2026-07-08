const TELEGRAM_LIMIT = 4096;

export function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function splitMessage(text: string, limit = TELEGRAM_LIMIT): string[] {
  if (text.length <= limit) return [text];
  const chunks: string[] = [];
  let current = "";
  for (const para of text.split("\n\n")) {
    const candidate = current ? `${current}\n\n${para}` : para;
    if (candidate.length > limit && current) {
      chunks.push(current);
      current = para;
    } else {
      current = candidate;
    }
  }
  if (current) chunks.push(current);
  // A single paragraph longer than the limit is still possible in theory.
  return chunks.flatMap((c) => {
    const parts: string[] = [];
    for (let i = 0; i < c.length; i += limit) parts.push(c.slice(i, i + limit));
    return parts;
  });
}

export async function sendMessage(token: string, chatId: string | number, html: string): Promise<void> {
  for (const chunk of splitMessage(html)) {
    const resp = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        text: chunk,
        parse_mode: "HTML",
        disable_web_page_preview: true,
      }),
    });
    const payload = (await resp.json().catch(() => ({}))) as { ok?: boolean; description?: string };
    if (!payload.ok) {
      throw new Error(`sendMessage failed (${resp.status}): ${payload.description ?? "unknown"}`);
    }
  }
}

export async function sendTyping(token: string, chatId: string | number): Promise<void> {
  await fetch(`https://api.telegram.org/bot${token}/sendChatAction`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, action: "typing" }),
  }).catch(() => {});
}
