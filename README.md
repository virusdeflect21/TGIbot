# TGIbot — Telegram Chat Automation

A Python bot for Telegram's **profile Chat Automation / Connected Business Bots** feature. It connects as a bot account over Telegram's native MTProto update stream, processes only private business-chat updates, and sends replies through the business connection on behalf of the connected profile.

**This implementation does not call Bot API `getUpdates` and does not register a webhook.** Telegram's profile-side Chat Automation connection determines which chats are shared with the bot; the service uses MTProto's persistent connection to receive `updateBotBusinessConnect` / `updateBotNewBusinessMessage` updates and `invokeWithBusinessConnection` to reply. This is the native connected-bot path, not an HTTP webhook adapter.

## Telegram setup

1. Create a bot with [@BotFather](https://t.me/BotFather). In BotFather, enable **Business Mode** (also referred to as Secretary Mode in the bot guide) so the bot can be connected to a profile.
2. Create an app at [my.telegram.org](https://my.telegram.org) and note its **API ID** and **API hash**. Telegram requires app credentials for MTProto, including when authenticating as a bot.
3. In Telegram, open **Settings → Chat Automation**, connect the bot to the profile, select the private chats it may access, and grant the permission to reply.
4. Run a single service instance for this bot token. Do not run this alongside another program that logs in as the same bot. If you replace the bot token, remove `telegram-session.session` from the persistent disk so MTProto authenticates as the new bot.

The profile owner remains in control of the allowed chats and permissions. The bot ignores messages sent by the profile owner and ignores groups/channels.

## Commands (private chats only)

- `/spam <number> <text>` — sends `<text>` as `<number>` separate messages to the person who issued the command. The count is restricted to **1–10**, text must fit in one Telegram message, and the command is limited to **one use per chat per 60 seconds**. Sends are paced at about one message per second. A successful command has no extra confirmation message, so it sends exactly the requested number.
- `/copy` — toggle copy mode. `/copy on` and `/copy off` are explicit alternatives. In copy mode, new messages from the other participant are copied back into that same DM. Text entities are preserved; supported photos, documents, contacts, locations, polls, and similar Telegram media are re-sent from their existing Telegram file references. Some protected/service/unsupported message types and inline-keyboard callbacks cannot be reproduced; media albums are copied as individual messages.
- `/autobot` — toggle AI replies. `/autobot on` and `/autobot off` are explicit alternatives. AI replies use OrcaRouter's `deepseek/deepseek-v4-flash-free` model. Every non-command incoming message triggers an AI request; text and captions are passed as text, while media-only messages are represented by a short type-only note. The model never receives media bytes and is instructed not to claim it can see an attachment. It retains a short per-DM text history for context.

Copy and autobot are mutually exclusive. Enabling either turns the other off. Modes persist for each `(business connection, private chat)` until switched off; they survive process restarts when the Render disk is attached. `/autobot off` is never rate-limited. Enabling autobot is limited to 3 activations per 5 minutes, and AI calls are limited to 12 per private chat per hour. These limits, plus the spam cooldown, are stored in SQLite rather than reset on each process restart.

## Configuration

The Render Blueprint prompts for the four credentials below. Do not commit these values or put them in source code.

| Environment variable | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Token from @BotFather |
| `TELEGRAM_API_ID` | Telegram app ID from my.telegram.org |
| `TELEGRAM_API_HASH` | Telegram app hash from my.telegram.org |
| `ORCAROUTER_API_KEY` | OrcaRouter API key |
| `DATA_DIR` | Runtime state directory; set to `/var/data` on Render by the Blueprint |

OrcaRouter calls `https://api.orcarouter.ai/v1/chat/completions` with the OpenAI-compatible `messages` payload. Requests have bounded connection/read timeouts. Timeouts, connection failures, malformed responses, upstream errors, and HTTP 429s are logged and receive a safe user-facing error; prompts and API keys are not written to logs.

## Deploy to Render

1. Push this repository to a Git provider connected to Render.
2. In Render, create a **Blueprint** from the repository and provide the four credential values when prompted.
3. Deploy. The included `render.yaml` installs `requirements.txt`, runs one Uvicorn worker on Render's `$PORT`, exposes `/health`, and attaches a 1 GB persistent disk at `/var/data` for the SQLite state and Telethon session.

The Blueprint selects a paid **Starter web service** intentionally: Telegram updates arrive over an outbound persistent MTProto connection, and an always-on bot must not sleep. Render Free web services spin down after 15 minutes without inbound HTTP/WebSocket traffic and lose local filesystem changes on spin-down/redeploy. A Free service can be used for a short-lived experiment, but it cannot reliably provide always-on Chat Automation or durable local SQLite/session state. The paid disk also means Render will stop the old instance before replacing it during a deploy; keep the service at one instance.

### Local run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN='…'
export TELEGRAM_API_ID='…'
export TELEGRAM_API_HASH='…'
export ORCAROUTER_API_KEY='…'
export DATA_DIR='./data'
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
```

A healthy process returns `{"status":"ok"}` from `/health` only while its MTProto connection is connected. Uvicorn's ASGI lifespan closes the Telegram client and HTTP client on shutdown; SQLite transactions make mode changes atomic. Keep the service at one instance because Telegram's session and local SQLite database are single-instance state.

## State, privacy, and operations

`state.py` stores connection permissions, copy/autobot modes, rate-limit windows, and recent AI conversation turns in SQLite. SQLite uses transactions, WAL, and `synchronous=FULL`; the Telegram MTProto authorization session is stored separately in the same data directory and restricted to owner-readable permissions where supported. The last 24 AI history messages per conversation are retained for context and history older than 30 days is pruned when the service starts. Text and captions in autobot-enabled chats are sent to OrcaRouter; media bytes are not. Do not share or expose the persistent disk.

Logs are newline-delimited JSON with UTC timestamps, event names, connection/chat/user IDs, command names, API status, and elapsed time. Message contents and secrets are intentionally excluded.

## Tests

Run the parser, mode persistence, rate-limit, history-isolation, and Unicode-length checks with:

```bash
python -m unittest discover -s tests -v
```

## Sources

- Telegram announcement of [Chat Automation in Profiles](https://telegram.org/blog/ai-bot-revolution-11-new-features) (May 7, 2026).
- Official [Connected Business Bots MTProto guide](https://core.telegram.org/api/bots/connected-business-bots) — connection IDs, business updates, rights, and `invokeWithBusinessConnection`.
- Official [Working with bots over MTProto](https://core.telegram.org/api/bots) — bot-token authorization using Telegram app credentials.
- [OrcaRouter Quickstart](https://docs.orcarouter.ai/getting-started/quickstart) and the [DeepSeek V4 Flash Free model reference](https://www.orcarouter.ai/models/deepseek/deepseek-v4-flash-free) — base URL, chat-completions schema, and model ID.
- Render docs: [Free service limits](https://docs.render.com/free), [persistent disks](https://docs.render.com/disks), and [Blueprint YAML](https://docs.render.com/blueprint-spec).
