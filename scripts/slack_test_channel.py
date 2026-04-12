#!/usr/bin/env python3
"""Test Slack channel join and print channel id. Usage: load .env then run from repo root."""
import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        print("SLACK_BOT_TOKEN missing", file=sys.stderr)
        return 1
    ch = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SLACK_CHANNEL", "#launches")).strip()
    if ch.startswith("#"):
        ch = ch[1:]
    r = requests.post(
        "https://slack.com/api/conversations.join",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        json={"channel": ch},
        timeout=60,
    )
    data = r.json()
    print(json.dumps(data, indent=2))
    if data.get("ok") and data.get("channel"):
        print("\nUse in .env:\nSLACK_CHANNEL=" + str(data["channel"]["id"]), file=sys.stderr)
    return 0 if data.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
