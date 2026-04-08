"""QA agent: review HTML and marketing copy; post inline PR comments; report to CEO."""
from __future__ import annotations

import json
import os
from typing import Any

import requests

from agents.engineer_agent import GITHUB_API, _headers, _repo_parts
from agents.utils import iso_timestamp, new_message_id
from llm import call_llm, parse_json_from_llm
from message_bus import MessageBus
from schemas import make_message


def _review_with_llm(html: str, marketing: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    system = """You are a strict QA reviewer. Return JSON only:
{
  "verdict": "pass" or "fail",
  "issues": ["specific issue 1", ...],
  "html_comment_1": "short inline comment for line 1 area",
  "html_comment_2": "short inline comment for another line area"
}
Use fail if headline mismatches value proposition, features missing, or marketing tone is off."""
    user = (
        f"Value proposition: {spec.get('value_proposition','')}\n\n"
        f"Marketing JSON: {json.dumps(marketing, indent=2)[:4000]}\n\n"
        f"HTML (truncated to 12000 chars):\n{html[:12000]}"
    )
    text = call_llm(system, user, max_tokens=2048)
    raw = parse_json_from_llm(text)
    if not isinstance(raw, dict):
        raise ValueError("QA review JSON invalid")
    verdict = str(raw.get("verdict", "fail")).lower()
    issues = raw.get("issues") or []
    if not isinstance(issues, list):
        issues = []
    return {
        "verdict": "pass" if verdict == "pass" else "fail",
        "issues": [str(x) for x in issues][:20],
        "html_comment_1": str(raw.get("html_comment_1", "Check semantic structure."))[:500],
        "html_comment_2": str(raw.get("html_comment_2", "Verify CTA visibility."))[:500],
    }


def _post_pr_line_comment(
    owner: str,
    repo: str,
    pull_number: int,
    commit_id: str,
    path: str,
    line: int,
    body: str,
) -> None:
    r = requests.post(
        f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_number}/comments",
        headers=_headers(),
        json={
            "body": body,
            "commit_id": commit_id,
            "path": path,
            "line": line,
            "side": "RIGHT",
        },
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"GitHub PR comment failed: {r.status_code} {r.text[:500]}")


def process_inbox(bus: MessageBus) -> None:
    for msg in bus.receive_all("qa"):
        if msg["message_type"] != "task":
            continue
        payload = msg["payload"]
        html = str(payload.get("html", ""))
        marketing = payload.get("marketing_copy") or {}
        spec = payload.get("product_spec") or {}
        pr_number = int(payload.get("pr_number", 0))
        head_sha = str(payload.get("head_sha", ""))
        path = str(payload.get("landing_path", "index.html"))
        parent = msg.get("message_id")

        review = _review_with_llm(html, marketing, spec)

        owner, repo = _repo_parts()
        lines = html.splitlines()
        n = max(1, len(lines))
        line1 = 1
        line2 = min(n, max(2, n // 2))
        try:
            _post_pr_line_comment(owner, repo, pr_number, head_sha, path, line1, f"QA: {review['html_comment_1']}")
            _post_pr_line_comment(owner, repo, pr_number, head_sha, path, line2, f"QA: {review['html_comment_2']}")
        except Exception as exc:
            review["issues"].append(f"Inline comment post failed: {exc}")

        bus.send(
            make_message(
                message_id=new_message_id(),
                from_agent="qa",
                to_agent="ceo",
                message_type="result",
                payload={
                    "verdict": review["verdict"],
                    "issues": review["issues"],
                    "inline_comments_posted": True,
                },
                timestamp=iso_timestamp(),
                parent_message_id=parent,
            )
        )
        bus.send(
            make_message(
                message_id=new_message_id(),
                from_agent="qa",
                to_agent="ceo",
                message_type="confirmation",
                payload={"status": "qa_complete"},
                timestamp=iso_timestamp(),
                parent_message_id=parent,
            )
        )
