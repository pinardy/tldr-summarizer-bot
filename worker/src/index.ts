import { Env } from "./ai";
import { handleDigest, handleHelp, handleQuestion } from "./commands";
import { sendMessage } from "./telegram";

interface TelegramUpdate {
  update_id?: number;
  message?: {
    text?: string;
    chat?: { id: number };
  };
}

async function handleUpdate(env: Env, update: TelegramUpdate): Promise<void> {
  const chatId = update.message?.chat?.id;
  const text = update.message?.text?.trim();
  if (!chatId || !text) return; // ignore non-text updates (photos, edits, ...)

  if (String(chatId) !== env.ALLOWED_CHAT_ID) {
    await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId, "Sorry, this is a private bot.").catch(
      () => {}
    );
    return;
  }

  try {
    if (text === "/start" || text === "/help") {
      await handleHelp(env, chatId);
    } else if (text === "/digest") {
      await handleDigest(env, chatId);
    } else if (text.startsWith("/news")) {
      const topic = text.slice(5).trim();
      await handleQuestion(
        env,
        chatId,
        topic ? `What are today's stories about: ${topic}?` : "What are today's top stories?"
      );
    } else if (text.startsWith("/")) {
      await handleHelp(env, chatId);
    } else {
      await handleQuestion(env, chatId, text);
    }
  } catch (e) {
    console.error("handler failed:", e);
    await sendMessage(
      env.TELEGRAM_BOT_TOKEN,
      chatId,
      "⚠️ Something went wrong handling that — try again in a minute."
    ).catch(() => {});
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "POST" && url.pathname === "/webhook") {
      if (request.headers.get("x-telegram-bot-api-secret-token") !== env.WEBHOOK_SECRET) {
        return new Response("unauthorized", { status: 401 });
      }
      const update = (await request.json().catch(() => null)) as TelegramUpdate | null;
      if (!update) return new Response("ok");

      // Telegram retries slow webhooks with the same update_id — dedupe so a
      // retry doesn't reprocess while the original invocation is still working.
      if (update.update_id !== undefined) {
        const seenKey = `seen:${update.update_id}`;
        if (await env.STORE.get(seenKey)) return new Response("ok");
        await env.STORE.put(seenKey, "1", { expirationTtl: 600 });
      }

      // Do the work within the request lifetime: the invocation stays alive
      // while Telegram waits for the response, and waitUntil grants a +30s
      // grace window if Telegram disconnects first. (waitUntil alone is NOT
      // enough — it is capped at 30s, shorter than an LLM merge call.)
      const work = handleUpdate(env, update);
      ctx.waitUntil(work);
      await work;
      return new Response("ok");
    }

    return new Response("tldr-bot", { status: 200 });
  },
};
