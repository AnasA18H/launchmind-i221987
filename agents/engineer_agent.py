"""Engineer agent: product spec -> HTML landing page + GitHub issue, branch, commit, PR."""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any
from uuid import uuid4

import requests

from agents.utils import iso_timestamp, new_message_id
from llm import call_llm
from message_bus import MessageBus
from schemas import make_message

GITHUB_API = "https://api.github.com"


def _headers() -> dict[str, str]:
    token = os.environ["GITHUB_TOKEN"]
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo_parts() -> tuple[str, str]:
    repo = os.environ.get("GITHUB_REPO", "")
    if "/" not in repo:
        raise ValueError("GITHUB_REPO must be owner/name")
    owner, name = repo.split("/", 1)
    return owner, name


def _generate_html(spec: dict[str, Any]) -> str:
    system = """You are a front-end developer. Produce a single self-contained HTML file for a startup landing page.
Include: headline, subheadline, a features section (from the spec), a clear CTA button, and embedded CSS in <style>.
Use semantic HTML5, readable fonts, and a cohesive color scheme. Output only the raw HTML document, no markdown."""
    user = f"Product specification JSON:\n{json.dumps(spec, indent=2)}\n\nReturn complete HTML only."
    text = call_llm(system, user, max_tokens=8192)
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:html)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    if "<html" not in text.lower():
        raise ValueError("LLM did not return valid HTML")
    return text


def _create_issue(owner: str, repo: str, title: str, body: str) -> str:
    r = requests.post(
        f"{GITHUB_API}/repos/{owner}/{repo}/issues",
        headers=_headers(),
        json={"title": title, "body": body},
        timeout=60,
    )
    r.raise_for_status()
    return str(r.json()["html_url"])


def _get_ref_sha(owner: str, repo: str, ref: str) -> str:
    r = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/git/ref/heads/{ref}",
        headers=_headers(),
        timeout=60,
    )
    r.raise_for_status()
    return str(r.json()["object"]["sha"])


def _create_branch(owner: str, repo: str, branch: str, sha: str) -> None:
    r = requests.post(
        f"{GITHUB_API}/repos/{owner}/{repo}/git/refs",
        headers=_headers(),
        json={"ref": f"refs/heads/{branch}", "sha": sha},
        timeout=60,
    )
    if r.status_code == 422:
        return
    r.raise_for_status()


def _get_file_sha(owner: str, repo: str, path: str, ref: str) -> str | None:
    r = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
        headers=_headers(),
        params={"ref": ref},
        timeout=60,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return str(r.json()["sha"])


def _put_file(
    owner: str,
    repo: str,
    path: str,
    content: str,
    branch: str,
    message: str,
) -> None:
    b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    body: dict[str, Any] = {
        "message": message,
        "content": b64,
        "branch": branch,
        "author": {"name": "EngineerAgent", "email": "agent@launchmind.ai"},
        "committer": {"name": "EngineerAgent", "email": "agent@launchmind.ai"},
    }
    existing = _get_file_sha(owner, repo, path, branch)
    if existing:
        body["sha"] = existing
    r = requests.put(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
        headers=_headers(),
        json=body,
        timeout=120,
    )
    r.raise_for_status()


def _create_pr(owner: str, repo: str, title: str, body: str, head: str, base: str) -> dict[str, Any]:
    r = requests.post(
        f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
        headers=_headers(),
        json={"title": title, "body": body, "head": head, "base": base},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _issue_body_from_llm(spec: dict[str, Any]) -> str:
    system = "You write concise GitHub issue descriptions. Output plain markdown only, no preamble."
    user = f"Write a short issue description for implementing the initial landing page for this product:\n{spec.get('value_proposition','')}"
    return call_llm(system, user, max_tokens=512)


def _pr_body_from_llm(spec: dict[str, Any]) -> str:
    system = "You write concise GitHub PR descriptions. Output plain markdown only."
    user = f"Write a PR body for the landing page PR. Product: {spec.get('value_proposition','')}"
    return call_llm(system, user, max_tokens=512)


def run_github_workflow(spec: dict[str, Any], html: str) -> dict[str, Any]:
    owner, repo = _repo_parts()
    base = os.environ.get("GITHUB_BASE_BRANCH", "main")
    branch = f"agent-landing-{str(uuid4())[:8]}"
    issue_body = _issue_body_from_llm(spec)
    issue_url = _create_issue(owner, repo, "Initial landing page", issue_body)
    base_sha = _get_ref_sha(owner, repo, base)
    _create_branch(owner, repo, branch, base_sha)
    path = os.environ.get("GITHUB_LANDING_PATH", "index.html")
    _put_file(owner, repo, path, html, branch, "Add landing page")
    pr_title = "Initial landing page"
    pr_body = _pr_body_from_llm(spec)
    pr = _create_pr(owner, repo, pr_title, pr_body, branch, base)
    return {
        "issue_url": issue_url,
        "pr_url": pr["html_url"],
        "pr_number": int(pr["number"]),
        "branch": branch,
        "head_sha": pr["head"]["sha"],
        "base": base,
        "path": path,
    }


def process_inbox(bus: MessageBus) -> None:
    for msg in bus.receive_all("engineer"):
        if msg["message_type"] not in ("task", "revision_request"):
            continue
        payload = msg["payload"]
        spec = payload.get("product_spec") or {}
        parent = msg.get("message_id")
        revision_notes = payload.get("revision_notes")
        if msg["message_type"] == "revision_request" and isinstance(revision_notes, str):
            spec = {**spec, "_qa_revision_notes": revision_notes}
        html = _generate_html(spec)
        meta = run_github_workflow(spec, html)
        bus.send(
            make_message(
                message_id=new_message_id(),
                from_agent="engineer",
                to_agent="ceo",
                message_type="result",
                payload={
                    "html": html,
                    "issue_url": meta["issue_url"],
                    "pr_url": meta["pr_url"],
                    "pr_number": meta["pr_number"],
                    "branch": meta["branch"],
                    "head_sha": meta["head_sha"],
                    "landing_path": meta["path"],
                },
                timestamp=iso_timestamp(),
                parent_message_id=parent,
            )
        )
        bus.send(
            make_message(
                message_id=new_message_id(),
                from_agent="engineer",
                to_agent="ceo",
                message_type="confirmation",
                payload={"status": "engineer_complete", "pr_url": meta["pr_url"]},
                timestamp=iso_timestamp(),
                parent_message_id=parent,
            )
        )
