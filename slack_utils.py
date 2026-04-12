"""Slack helpers: join channel by name or ID, then post (no conversations.list)."""
from __future__ import annotations

import os
import re
from typing import Any

import requests

_SLACK_JSON = "application/json; charset=utf-8"
_CHANNEL_ID = re.compile(r"^[CG][A-Z0-9]{8,}$")


def slack_auth_headers(token: str | None = None) -> dict[str, str]:
    t = token or os.environ["SLACK_BOT_TOKEN"]
    return {"Authorization": f"Bearer {t}", "Content-Type": _SLACK_JSON}


def _find_channel_id_among_bot_channels(token: str, name: str) -> str | None:
    """
    Bot tokens only list channels the bot has joined. Public channels only (no groups:read).
    """
    want_clean = name.strip().lstrip("#").lower()
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"types": "public_channel", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(
            "https://slack.com/api/conversations.list",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=60,
        )
        data = r.json()
        if not data.get("ok"):
            return None
        for c in data.get("channels", []):
            if (c.get("name") or "").lower() == want_clean:
                return str(c["id"])
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break
    return None


def join_and_get_channel_id(channel_setting: str) -> str:
    """
    Join the channel (public) and return its ID for chat.postMessage.

    Uses conversations.join with channel *name* or *ID* — no conversations.list.
    Bot tokens only see channels they're in when listing; joining by name avoids that.
    """
    raw = channel_setting.strip()
    if _CHANNEL_ID.match(raw):
        ch = raw
    else:
        ch = raw[1:] if raw.startswith("#") else raw

    token = os.environ["SLACK_BOT_TOKEN"]
    r = requests.post(
        "https://slack.com/api/conversations.join",
        headers=slack_auth_headers(token),
        json={"channel": ch},
        timeout=60,
    )
    data = r.json()
    if data.get("ok") and data.get("channel"):
        return str(data["channel"]["id"])

    err = data.get("error", "")
    if err == "channel_not_found":
        # Join-by-name can fail even when the channel exists (workspace/token quirks).
        # If the bot is already in the channel, conversations.list will still return it.
        alt = _find_channel_id_among_bot_channels(token, ch)
        if alt:
            return alt
        raise RuntimeError(
            f'Slack channel "{ch}" was not found. Fix one of these:\n'
            f'  1) Confirm SLACK_BOT_TOKEN is from the **same workspace** as #launches (re-copy xoxb- from OAuth & Permissions).\n'
            f'  2) Set SLACK_CHANNEL to the Channel ID: open #launches → title → About → copy ID (starts with C).\n'
            f'  3) Ensure the bot was added to #launches and the channel is **public**.\n'
        )
    if err in ("is_archived", "not_in_channel"):
        raise RuntimeError(
            f"Slack conversations.join failed ({err}): {data}. "
            "For private channels, invite the bot and set SLACK_CHANNEL to the channel ID (C…)."
        )
    raise RuntimeError(f"Slack conversations.join failed: {data}")


def slack_chat_post_message(payload: dict[str, Any]) -> dict[str, Any]:
    """POST chat.postMessage after joining the configured channel."""
    token = os.environ["SLACK_BOT_TOKEN"]
    channel_setting = os.environ.get("SLACK_CHANNEL", "#launches")
    channel_id = join_and_get_channel_id(channel_setting)
    payload = {**payload, "channel": channel_id}
    r = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=slack_auth_headers(token),
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API error: {data}")
    return data
