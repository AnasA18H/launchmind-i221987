#!/usr/bin/env python3
"""Optional smoke checks: GitHub user, Slack auth.test, SendGrid (dry if no key). Run from repo root with .env loaded."""
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    ok = True
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN: missing")
        ok = False
    else:
        r = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
            timeout=30,
        )
        print(f"GitHub /user: {r.status_code} {r.json().get('login', r.text[:200])}")
        ok = ok and r.status_code == 200

    slack = os.environ.get("SLACK_BOT_TOKEN")
    if not slack:
        print("SLACK_BOT_TOKEN: missing")
        ok = False
    else:
        r = requests.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {slack}"},
            timeout=30,
        )
        j = r.json()
        print(f"Slack auth.test: ok={j.get('ok')} team={j.get('team')}")
        ok = ok and j.get("ok") is True

    sg = os.environ.get("SENDGRID_API_KEY")
    if not sg:
        print("SENDGRID_API_KEY: missing (required for Marketing email)")
    else:
        print("SENDGRID_API_KEY: present")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
