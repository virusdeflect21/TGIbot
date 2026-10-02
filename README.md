# TGIbot — Telegram Chat Automation

A Python bot for Telegram's **profile Chat Automation / Connected Business Bots** feature. It connects as a bot account over Telegram's native MTProto update stream, processes only private business-chat updates, and sends replies through the business connection on behalf of the connected profile.

**This implementation does not call Bot API `getUpdates` and does not register a webhook.** Telegram's profile-side Chat Automation connection determines which chats are shared with the bot; the service uses MTProto's persistent connection to receive `updateBotBusinessConnect` / `updateBotNewBusinessMessage` updates and `invokeWithBusinessConnection` to reply. This is the native connected-bot path, not an HTTP webhook adapter.

## Run it locally

Download the **Source code (zip)** from the GitHub **Releases** page and extract it. Copy `config.example.py` to `config.py`, add your Telegram credentials, install Python 3.12 and the pinned packages, then start the bot with `python run.py`. The complete Windows/macOS/Linux walkthrough, Telegram setup, and troubleshooting steps are in [LOCAL_SETUP.md](LOCAL_SETUP.md).

No Docker, Node.js, or separate database is needed. The computer must stay online with the bot process running. `config.py` is local-only, ignored by Git, and intentionally not included in the release ZIP.

## Telegram setup

1. Create a bot with [@BotFather](https://t.me/BotFather). In BotFather, enable **Business Mode** (also referred to as Secretary Mode in the bot guide) so the bot can be connected to a profile.
2. Create an app at [my.telegram.org](https://my.telegram.org) and note its **API ID** and **API hash**. Telegram requires app credentials for MTProto, including when authenticating as a bot.
3. In Telegram, open **Settings → Chat Automation**, connect the bot to the profile, select the private chats it may access, and grant the permission to reply. To use `/mute`, also grant **Delete received messages**.
4. Run a single service instance for this bot token. Do not run this alongside another program that logs in as the same bot. If you replace the bot token, remove `telegram-session.session` from the configured data directory before starting the new token; on Render Free, a fresh deploy normally starts with a new temporary filesystem.

The profile owner remains in control of the allowed chats and permissions. The bot ignores the profile owner's regular messages and ignores groups/channels; the owner can issue `/mute` and `/unmute` from a private DM.

## Commands (private chats only)

- `/spam <number> <text>` — sends `<text>` as `<number>` separate messages to the person who issued the command. The count is restricted to **1–10**, text must fit in one Telegram message, and the command is limited to **one use per chat per 60 seconds**. Sends are paced at about one message per second. A successful command has no extra confirmation message, so it sends exactly the requested number.
- `/copy` — toggle copy mode. `/copy on` and `/copy off` are explicit alternatives. In copy mode, new messages from the other participant are copied back into that same DM. Text entities are preserved; supported photos, documents, contacts, locations, polls, and similar Telegram media are re-sent from their existing Telegram file references. Some protected/service/unsupported message types and inline-keyboard callbacks cannot be reproduced; media albums are copied as individual messages.
- `/autobot` — toggle AI replies. `/autobot on` and `/autobot off` are explicit alternatives. AI replies use OrcaRouter's `deepseek/deepseek-v4-flash-free` model. Every non-command incoming message triggers an AI request; text and captions are passed as text, while media-only messages are represented by a short type-only note. The model never receives media bytes and is instructed not to claim it can see an attachment. It retains a short per-DM text history for context.
- `/mute` — delete each new incoming message in this private DM for both sides, until `/unmute`. `/mute on` is also accepted. It does not delete messages already in the chat. While muted, only `/mute` and `/unmute` commands are processed; other incoming commands/messages are deleted too. Requires the Telegram **Delete received messages** business permission.
- `/unmute` — stop deleting new incoming messages in this DM. `/unmute off` is also accepted. This command is checked before mute filtering so it remains usable while muted.

Only the connected profile owner can issue `/mute` or `/unmute`; other participants cannot change mute state.

Copy and autobot are mutually exclusive. Mute is an independent override: while muted, copy and AI replies pause, then resume after `/unmute` if their mode is still enabled. Modes persist for each `(business connection, private chat)` until switched off; they survive process restarts when the Render disk is attached. `/autobot off` is never rate-limited. Enabling autobot is limited to 3 activations per 5 minutes, and AI calls are limited to 12 per private chat per hour. These limits, plus the spam cooldown, are stored in SQLite rather than reset on each process restart.

## Configuration

For a local run, copy `config.example.py` to `config.py` and fill in `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID`, and `TELEGRAM_API_HASH`. `ORCAROUTER_API_KEY` is optional unless you want `/autobot`. `DATA_DIR` defaults to `./data`. The app reads environment variables first (useful for Render/hosting), then falls back to the adjacent local `config.py` file. Never commit or share real credentials; `config.py` is ignored by Git and excluded from release ZIPs.

| Setting | Required? | Purpose |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | Yes | Token from @BotFather |
| `TELEGRAM_API_ID` | Yes | Telegram app ID from my.telegram.org |
| `TELEGRAM_API_HASH` | Yes | Telegram app hash from my.telegram.org |
| `ORCAROUTER_API_KEY` | Only for `/autobot` | OrcaRouter API key for AI replies |
| `DATA_DIR` | No | State/session directory (defaults to `./data`; on Render, use a mount path only with a persistent disk) |

OrcaRouter calls `https://api.orcarouter.ai/v1/chat/completions` with the OpenAI-compatible `messages` payload. Requests have bounded connection/read timeouts. Timeouts, connection failures, malformed responses, upstream errors, and HTTP 429s are logged and receive a safe user-facing error; prompts and API keys are not written to logs.

## Deploy to Render manually (no Blueprint)

This project can be deployed as a regular Render **Web Service**. You do not need a Blueprint, Docker, a separate database service, or a computer running at home.

1. Push this repository to GitHub, GitLab, or another Git provider connected to Render.
2. In the Render Dashboard, choose **New → Web Service** (not **Blueprint**) and connect the repository. Select the branch containing this code and leave **Root Directory** blank.
3. Set **Language** to **Python 3** and **Instance Type** to **Free**.
4. Enter these commands:

   | Render setting | Value |
   | --- | --- |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1` |
   | Health Check Path | `/health` (under **Advanced**) |

5. In **Environment**, add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID`, and `TELEGRAM_API_HASH` with the values from the setup steps above. Add `ORCAROUTER_API_KEY` only if you want `/autobot`. On Free, leave `DATA_DIR` unset and do not add a disk.
6. Click **Create Web Service**. Once the deploy is live, `https://<your-service>.onrender.com/health` should return `{"status":"ok"}` after Telegram connects. `/ping` is a lightweight liveness endpoint and returns `{"status":"alive"}` while the web process is serving requests.

After deployment, connect the bot to your Telegram profile under **Settings → Chat Automation**, choose the chats and permissions it may access, and use `/autobot on` or `/copy on` in the private chat where you want that mode. The bot receives updates over MTProto; no Telegram webhook URL or Bot API polling configuration is needed.

### Render Free tier: automatic keep-alive and important limits

A Free Render service is a best-effort hobby deployment, not a reliable always-on bot:

- Render can spin a Free web service down after 15 minutes without inbound HTTP traffic. The bot uses an outbound MTProto connection, so Telegram updates alone do not keep the web service awake. On Render, the app now automatically reads Render's `RENDER_EXTERNAL_URL` and sends a lightweight `GET /ping` to itself every 10 minutes—no extra environment variable, GitHub Action, or external host is needed. This is best-effort: a self-ping might not prevent every spin-down, and the app cannot wake itself if it has already stopped. The first external request after sleep can take about a minute to wake it.
- Free services have no persistent disk. Render can also restart them at any time, and files are lost on spin-down, restart, or redeploy. The bot authenticates again from its bot token, but the SQLite connection cache, modes, rate-limit windows, and AI history are temporary. After a restart, `/autobot`, `/copy`, and `/mute` are off and must be enabled again. Messages arriving while the bot is disconnected are not guaranteed to be handled.
- Render's 750 free instance hours are shared across your workspace. If the service stays awake continuously, it can use nearly all of that allowance.

For dependable always-on operation and state that survives restarts, use a paid Render service with a persistent disk. The automatic self-ping is a convenience for hobby use, not a guarantee of 24/7 delivery.

### Local run

See the step-by-step [local setup guide](LOCAL_SETUP.md) for Python installation, the private `config.py` file, virtual-environment commands for Windows/macOS/Linux, and Telegram profile setup. Once packages are installed and credentials are configured, run:

```bash
python run.py
```

The local launcher binds to `127.0.0.1:8000`. A healthy process returns `{"status":"ok"}` from `/health` only while its MTProto connection is connected. Uvicorn's ASGI lifespan closes the Telegram client and HTTP client on shutdown; SQLite transactions make mode changes atomic. Keep the service at one instance because Telegram's session and local SQLite database are single-instance state.

## State, privacy, and operations

`state.py` stores connection permissions, copy/autobot/mute modes, rate-limit windows, and recent AI conversation turns in SQLite. SQLite uses transactions, WAL, and `synchronous=FULL`. The runtime data directory is restricted to owner-only access where supported; the database, SQLite WAL/shared-memory sidecars, and Telegram MTProto authorization session are also restricted to owner-only permissions. The last 24 AI history messages per conversation are retained for context and history older than 30 days is pruned when the service starts. Text and captions in autobot-enabled chats are sent to OrcaRouter; media bytes are not. Mute deletes only new incoming messages after activation, and only when Telegram's `delete_received_messages` permission is present. Do not share or expose the persistent disk.

Logs are newline-delimited JSON with UTC timestamps, event names, connection/chat/user IDs, command names, API status, and elapsed time. Message contents and secrets are intentionally excluded.

## Release ZIP

The source tree includes a safe ZIP builder. From the repository root, run `python scripts/build_release.py 1.0.0`; it writes `dist/TGIbot-local-v1.0.0.zip`. The builder includes only an explicit file allowlist, so `config.py`, Telegram sessions, databases, and virtual environments are not packaged.

## Tests

Run the parser, local/environment configuration, mode persistence/migrations, mute behavior, delete-permission, keep-alive URL, release-archive safety, rate-limit, history-isolation, and Unicode-length checks with:

```bash
python -m unittest discover -s tests -v
```

## Sources

- Telegram announcement of [Chat Automation in Profiles](https://telegram.org/blog/ai-bot-revolution-11-new-features) (May 7, 2026).
- Official [Connected Business Bots MTProto guide](https://core.telegram.org/api/bots/connected-business-bots) — connection IDs, business updates, deletion methods, rights, and `invokeWithBusinessConnection`.
- Official [BusinessBotRights reference](https://core.telegram.org/constructor/businessBotRights) — `delete_received_messages` controls deleting received messages in managed private chats.
- Official [Working with bots over MTProto](https://core.telegram.org/api/bots) — bot-token authorization using Telegram app credentials.
- [OrcaRouter Quickstart](https://docs.orcarouter.ai/getting-started/quickstart) and the [DeepSeek V4 Flash Free model reference](https://www.orcarouter.ai/models/deepseek/deepseek-v4-flash-free) — base URL, chat-completions schema, and model ID.
- Render docs: [Free service limits](https://docs.render.com/free), [default environment variables](https://docs.render.com/environment-variables), [deploying FastAPI](https://render.com/docs/deploy-fastapi), and [persistent disks](https://docs.render.com/disks).
