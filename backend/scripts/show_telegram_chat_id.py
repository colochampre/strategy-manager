"""Finds the chat id to put in ``TELEGRAM_CHAT_ID``.

A chat id does not exist until someone writes to the bot: Telegram creates it
for the conversation, and the Bot API will only reveal conversations the bot is
already part of. So the order matters — message the bot FIRST, run this second.

    1. Open Telegram, find the bot by the @name BotFather gave it, press Start
       and send it anything at all.
    2. Put the token in backend/.env as TELEGRAM_BOT_TOKEN (the chat id can
       stay empty for now).
    3. cd backend && uv run python scripts/show_telegram_chat_id.py

This is NOT a test. It needs a real token and talks to Telegram, which is why
it lives here and not under tests/ (CLAUDE.md rule 1). It reads the token from
the settings the app already loads, so the token never travels on a command
line and is never printed: only its last four characters are, the same standing
the credential scripts give an exchange key.

``getUpdates`` returns only what is still in the bot's update queue, which
Telegram keeps for 24 hours and drops as soon as a running bot consumes it. An
empty answer almost always means the message was never sent, not that something
is broken.
"""

import asyncio
import sys

import httpx

from strategy_manager.shared.config import get_settings

_API = "https://api.telegram.org"
_TIMEOUT_SECONDS = 10.0


def _chats(updates: list[dict[str, object]]) -> dict[str, str]:
    """Maps each chat id seen in the updates to a human description of it.

    Keyed by id so a person who sent five messages is listed once, and ordered
    by first appearance so the answer stays stable between runs.
    """
    found: dict[str, str] = {}
    for update in updates:
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            payload = update.get(key)
            if not isinstance(payload, dict):
                continue
            chat = payload.get("chat")
            if not isinstance(chat, dict):
                continue
            chat_id = str(chat.get("id"))
            title = chat.get("title") or " ".join(
                str(chat.get(part))
                for part in ("first_name", "last_name")
                if chat.get(part)
            )
            found.setdefault(chat_id, f"{chat.get('type', 'chat')}: {title or 'unnamed'}")
    return found


async def main() -> int:
    settings = get_settings()
    # Quotes and stray whitespace survive a .env round trip and produce a 401
    # that reads like a wrong token. Strip them here rather than making someone
    # spot an invisible character.
    token = settings.telegram_bot_token.strip().strip("\"'").strip()
    if not token:
        print(
            "TELEGRAM_BOT_TOKEN is not set. Put the token BotFather gave you in "
            "backend/.env and run this again.",
            file=sys.stderr,
        )
        return 1

    print(f"asking Telegram which chats bot ***{token[-4:]} can see")
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        # WHICH bot this token belongs to, before anything else. An empty
        # getUpdates reads identically whether nobody has written to the bot or
        # the token belongs to a DIFFERENT bot than the one that was messaged,
        # and the second is the likelier mistake when someone has several.
        identity = await client.get(f"{_API}/bot{token}/getMe")
        if identity.status_code == 200:
            bot = identity.json().get("result") or {}
            print(f"this token is @{bot.get('username', '?')} — message THAT bot")

        # A webhook silences getUpdates completely: Telegram delivers each
        # update to the configured URL instead of queueing it here. Worth
        # naming, because the symptom is an empty list rather than an error.
        hook = await client.get(f"{_API}/bot{token}/getWebhookInfo")
        if hook.status_code == 200 and (hook.json().get("result") or {}).get("url"):
            print(
                "\nThis bot has a webhook configured, so getUpdates will always "
                "come back empty. Remove it with deleteWebhook, or read the chat "
                "id from whatever receives that webhook.",
                file=sys.stderr,
            )
            return 1

        response = await client.get(f"{_API}/bot{token}/getUpdates")

    if response.status_code == 401:
        print(
            "Telegram rejected the token (401). Check it was copied whole, "
            "including the digits before the colon.",
            file=sys.stderr,
        )
        return 1
    if response.status_code != 200:
        # Deliberately not the body: an error body can echo the request URL,
        # and the token rides in that URL's path.
        print(f"Telegram answered HTTP {response.status_code}", file=sys.stderr)
        return 1

    body = response.json()
    updates = body.get("result") or []
    chats = _chats(updates)
    if not chats:
        print(
            "No conversations yet. Open Telegram, send the bot any message, "
            "then run this again. If you already did and a worker with "
            "ALERTS_ENABLED=true is running, it may have consumed the update — "
            "send another message with the worker stopped.",
            file=sys.stderr,
        )
        return 1

    print("\nchat id                  conversation")
    for chat_id, description in chats.items():
        print(f"{chat_id:<24} {description}")
    print("\nPut the id of YOUR conversation in backend/.env as TELEGRAM_CHAT_ID,")
    print("set ALERTS_ENABLED=true, then check the channel end to end with:")
    print("    uv run python scripts/send_test_alert.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
