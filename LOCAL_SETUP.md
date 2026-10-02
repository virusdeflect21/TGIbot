# Run TGIbot on your computer

This guide is for the downloadable `TGIbot-local-*.zip`. It runs the Telegram bot on your own Windows, macOS, or Linux computer; there is no hosting service, Docker, Node.js, or separate database to install.

## 1. Install Python

Install **Python 3.12** (recommended) from [python.org](https://www.python.org/downloads/). Python 3.11 also works with the included dependencies. On Windows, enable **Add Python to PATH** during installation. The bot needs an internet connection and must stay running to receive Telegram updates.

## 2. Get the Telegram credentials

You need these three values to start the bot:

1. **Bot token** — create a bot with [@BotFather](https://t.me/BotFather), enable Business Mode for it, then copy its token.
2. **Telegram API ID and API hash** — sign in at [my.telegram.org](https://my.telegram.org), open **API development tools**, and create an app if needed.
3. **OrcaRouter API key (optional)** — only needed for AI replies with `/autobot`. Without it, the bot still starts and `/spam`, `/copy`, `/mute`, and `/unmute` remain available.

Keep all of these credentials private. Do not paste them into chat, screenshots, or public source code.

## 3. Extract the ZIP and make your private config file

Extract the ZIP to a folder you control, for example `Documents/TGIbot`. Open a terminal in that folder and make a copy of the template:

```powershell
# Windows PowerShell
Copy-Item config.example.py config.py
notepad config.py
```

```bash
# macOS or Linux
cp config.example.py config.py
nano config.py
```

You can also use any text editor. Fill in the values in `config.py`:

```python
TELEGRAM_BOT_TOKEN = "paste-your-bot-token-here"
TELEGRAM_API_ID = "12345678"
TELEGRAM_API_HASH = "paste-your-api-hash-here"
ORCAROUTER_API_KEY = "paste-your-orcarouter-key-here"  # optional
DATA_DIR = "./data"
```

Keep the quotes. API ID can be left as a number or written as text. `config.py` is intentionally ignored by Git and is not included in the release ZIP; `config.example.py` is only a blank template. The app reads credentials from `config.py` first, while environment variables override it for hosted deployments.

## 4. Install the Python packages

Open a terminal **in the extracted TGIbot folder**.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell says scripts are disabled, either run the activation command shown by Python's virtual-environment documentation, or skip activation and use the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

### macOS or Linux

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If your system's Python command is already Python 3.12, you can use `python` instead of `python3.12` in the first command. The `.venv` folder is a private package environment for this project; it does not change system Python.

## 5. Start the bot

With the virtual environment activated, run:

```bash
python run.py
```

Leave this terminal open while you want the bot online. Stop it with **Ctrl+C**. The local status pages are:

- `http://127.0.0.1:8000/health` — returns `{"status":"ok"}` once Telegram is connected.
- `http://127.0.0.1:8000/ping` — confirms the local web process is running.

The bot binds to `127.0.0.1` only; you do not need to open a router port or expose it to the internet. Your computer must stay powered on, connected to the internet, and running this program for the bot to receive updates. Run only one copy at a time for the same bot token.

## 6. Connect it to your Telegram profile

In Telegram, open **Settings → Chat Automation**, connect this bot, choose which private chats it can access, and grant the permissions you need:

- **Reply** is needed for bot replies, commands, copy mode, and AI replies.
- **Delete received messages** is additionally needed for `/mute`.

Then use these commands in a private chat:

- `/spam 3 hello` — send the text three times (limited to 1–10 messages and one use per chat per minute).
- `/copy on` or `/copy off` — copy new messages in that DM back to the same DM.
- `/autobot on` or `/autobot off` — enable/disable AI replies. This requires `ORCAROUTER_API_KEY` in `config.py`.
- `/mute` and `/unmute` — delete new incoming messages until unmuted; only the profile owner can control this, and the delete permission is required.

Copy mode and autobot mode are mutually exclusive. The bot processes private one-to-one chats only. See the main [README](README.md) for the complete command behavior and privacy notes.

## Files and troubleshooting

- `config.py` — your private credentials. Never share this file.
- `data/telegram-session.session` — Telegram's local authorization session. Treat it like a password; do not share it.
- `data/tgibot.sqlite3` — saved modes, connection metadata, rate limits, and AI history.

**“Required setting … is missing”** — check that `config.py` is beside `app.py`, its name is exactly `config.py` (not `config.py.txt`), and required values are filled in. Windows may hide file extensions; enable **View → File name extensions** in File Explorer.

**Invalid API ID or token / Telegram connection errors** — check for copied whitespace and confirm the token and API ID/hash belong to the intended bot/app. For a changed bot token, stop the process and delete only `data/telegram-session.session` before starting again. Do not run two copies of the same bot simultaneously.

**`/autobot` says AI is not configured** — set `ORCAROUTER_API_KEY` in `config.py`, save it, and restart the bot. AI requests send text/captions to OrcaRouter; media bytes are not uploaded.
