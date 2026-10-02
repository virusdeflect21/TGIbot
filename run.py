"""Start TGIbot locally on this computer."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    try:
        port = int(os.environ.get("PORT", "8000"))
    except ValueError as exc:
        raise SystemExit("PORT must be a number between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("PORT must be a number between 1 and 65535")

    # Loopback-only binding keeps the local status page private to this machine.
    # workers=1 is important: Telegram MTProto sessions and SQLite are single-instance.
    uvicorn.run("app:app", host="127.0.0.1", port=port, workers=1)


if __name__ == "__main__":
    main()
