"""Marketing agent: product spec + PR URL -> copy, email (SendGrid), Slack Block Kit."""
from __future__ import annotations

import html
import json
import os
from typing import Any

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from agents.utils import iso_timestamp, new_message_id
from llm import call_llm, parse_json_from_llm
from message_bus import MessageBus
from schemas import make_message
from slack_utils import slack_chat_post_message


def _generate_copy(spec: dict[str, Any], pr_url: str) -> dict[str, Any]:
    system = """You are a growth marketer. Return a single JSON object only with keys:
- tagline: string, under 10 words
- landing_blurb: string, 2-3 sentences for a landing page
- email_subject: string
- email_body: string, plain text cold outreach to an early user or investor (professional)
- twitter_post: string
- linkedin_post: string
- instagram_post: string
Rules: valid JSON only. Use standard double quotes for keys and strings. Escape any double quote inside a string as \\".
Do not put raw line breaks inside string values — use \\n instead. No markdown fences."""
    user = f"Product spec:\n{json.dumps(spec, indent=2)}\nGitHub PR (for context): {pr_url}\n"
    text = call_llm(system, user, max_tokens=2048)
    try:
        raw = parse_json_from_llm(text)
    except json.JSONDecodeError:
        fix = call_llm(
            "The user message is broken JSON from another model. Output ONLY a valid JSON object with the same keys: "
            "tagline, landing_blurb, email_subject, email_body, twitter_post, linkedin_post, instagram_post. "
            "Escape quotes inside strings. No markdown, no explanation.",
            text[:16000],
            max_tokens=4096,
        )
        raw = parse_json_from_llm(fix)
    if not isinstance(raw, dict):
        raise ValueError("marketing copy must be a JSON object")
    return {
        "tagline": str(raw.get("tagline", "Your next launch")).strip(),
        "landing_blurb": str(raw.get("landing_blurb", "")).strip(),
        "email_subject": str(raw.get("email_subject", "Quick intro")).strip(),
        "email_body": str(raw.get("email_body", "")).strip(),
        "twitter_post": str(raw.get("twitter_post", "")).strip(),
        "linkedin_post": str(raw.get("linkedin_post", "")).strip(),
        "instagram_post": str(raw.get("instagram_post", "")).strip(),
    }


def _send_sendgrid(subject: str, body: str, to_email: str) -> None:
    from_email = os.environ["SENDGRID_FROM_EMAIL"]
    key = os.environ["SENDGRID_API_KEY"]
    message = Mail(
        from_email=from_email,
        to_emails=to_email,
        subject=subject,
        html_content=f"<pre style='font-family:sans-serif;white-space:pre-wrap'>{html.escape(body)}</pre>",
    )
    sg = SendGridAPIClient(key)
    try:
        sg.send(message)
    except Exception as exc:
        body = getattr(exc, "body", None)
        if body is None and hasattr(exc, "args") and exc.args:
            body = exc.args[0]
        detail = body.decode() if isinstance(body, (bytes, bytearray)) else (body or str(exc))
        raise RuntimeError(
            f"SendGrid error ({type(exc).__name__}). From={from_email!r} to={to_email!r}. "
            f"Check API key has Mail Send, sender is verified, and .env has no extra spaces. "
            f"Details: {detail}"
        ) from exc


def _post_slack_block_kit(tagline: str, description: str, pr_url: str) -> None:
    slack_chat_post_message(
        {
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f"New Launch: {tagline}", "emoji": True}},
                {"type": "section", "text": {"type": "mrkdwn", "text": description}},
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*GitHub PR:* <{pr_url}|View PR>"},
                        {"type": "mrkdwn", "text": "*Status:* Ready for review"},
                    ],
                },
            ],
        }
    )


def process_inbox(bus: MessageBus) -> None:
    for msg in bus.receive_all("marketing"):
        if msg["message_type"] != "task":
            continue
        payload = msg["payload"]
        spec = payload.get("product_spec") or {}
        pr_url = str(payload.get("pr_url", ""))
        if not pr_url:
            raise ValueError("Marketing task requires pr_url in payload before Slack post")
        parent = msg.get("message_id")
        copy_out = _generate_copy(spec, pr_url)
        to_email = os.environ.get("TEST_EMAIL", os.environ.get("TO_EMAIL", ""))
        if not to_email:
            raise RuntimeError("TEST_EMAIL or TO_EMAIL must be set for SendGrid")
        _send_sendgrid(copy_out["email_subject"], copy_out["email_body"], to_email)
        _post_slack_block_kit(copy_out["tagline"], copy_out["landing_blurb"], pr_url)
        bus.send(
            make_message(
                message_id=new_message_id(),
                from_agent="marketing",
                to_agent="ceo",
                message_type="result",
                payload={"marketing_copy": copy_out, "pr_url": pr_url},
                timestamp=iso_timestamp(),
                parent_message_id=parent,
            )
        )
        bus.send(
            make_message(
                message_id=new_message_id(),
                from_agent="marketing",
                to_agent="ceo",
                message_type="confirmation",
                payload={"status": "marketing_complete"},
                timestamp=iso_timestamp(),
                parent_message_id=parent,
            )
        )
