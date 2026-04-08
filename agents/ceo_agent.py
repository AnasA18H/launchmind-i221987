"""CEO agent: orchestrates tasks, LLM decomposition and reviews, decision log, final Slack summary."""
from __future__ import annotations

import json
import os
from typing import Any

import requests

from agents import marketing_agent, product_agent, qa_agent
from agents.engineer_agent import process_inbox as engineer_process
from agents.utils import iso_timestamp, new_message_id
from llm import call_llm, parse_json_from_llm
from message_bus import MessageBus
from schemas import make_message


def _slack_post_blocks(blocks: list[dict[str, Any]]) -> None:
    token = os.environ["SLACK_BOT_TOKEN"]
    channel = os.environ.get("SLACK_CHANNEL", "#launches")
    r = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"channel": channel, "blocks": blocks},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API error: {data}")


def decompose_idea(idea: str) -> dict[str, str]:
    system = """You are the CEO of a micro-startup. Break the startup idea into focused briefs for three functions.
Return JSON only with keys: product_focus, engineer_focus, marketing_focus.
Each value is 1-3 sentences. Do not hardcode generic filler—tie to the specific idea."""
    text = call_llm(system, f"Startup idea:\n{idea}\n", max_tokens=1024)
    raw = parse_json_from_llm(text)
    if not isinstance(raw, dict):
        raise ValueError("decomposition must be JSON object")
    return {
        "product_focus": str(raw.get("product_focus", "")).strip(),
        "engineer_focus": str(raw.get("engineer_focus", "")).strip(),
        "marketing_focus": str(raw.get("marketing_focus", "")).strip(),
    }


def review_product_spec(idea: str, spec: dict[str, Any]) -> dict[str, Any]:
    system = """Review this product specification. Return JSON only:
{"acceptable": true or false, "reason": "short explanation", "feedback": "specific revision instructions if not acceptable, else empty string"}
Be strict: personas and features must be concrete and tied to the idea."""
    user = f"Idea:\n{idea}\n\nSpec:\n{json.dumps(spec, indent=2)}"
    text = call_llm(system, user, max_tokens=1024)
    raw = parse_json_from_llm(text)
    if not isinstance(raw, dict):
        raise ValueError("review must be JSON object")
    acc = raw.get("acceptable", False)
    if isinstance(acc, str):
        acc = acc.lower() in ("true", "yes", "1")
    return {
        "acceptable": bool(acc),
        "reason": str(raw.get("reason", "")),
        "feedback": str(raw.get("feedback", "")),
    }


def final_summary_llm(idea: str, spec: dict[str, Any], pr_url: str, marketing: dict[str, Any]) -> str:
    system = "Write a concise executive summary (3-6 sentences) for the team Slack. Plain text, no markdown code fences."
    user = f"Idea: {idea}\nVP: {spec.get('value_proposition')}\nPR: {pr_url}\nTagline: {marketing.get('tagline','')}"
    return call_llm(system, user, max_tokens=512).strip()


class CEOAgent:
    def __init__(self, bus: MessageBus, startup_idea: str) -> None:
        self.bus = bus
        self.idea = startup_idea
        self.decision_log: list[dict[str, str]] = []

    def _log(self, decision: str, reason: str) -> None:
        self.decision_log.append({"decision": decision, "reason": reason})

    def _send(
        self,
        *,
        to_agent: str,
        message_type: str,
        payload: dict[str, Any],
        parent_message_id: str | None = None,
    ) -> str:
        mid = new_message_id()
        self.bus.send(
            make_message(
                message_id=mid,
                from_agent="ceo",
                to_agent=to_agent,
                message_type=message_type,
                payload=payload,
                timestamp=iso_timestamp(),
                parent_message_id=parent_message_id,
            )
        )
        return mid

    def run(self) -> dict[str, Any]:
        bus = self.bus
        idea = self.idea

        dec = decompose_idea(idea)
        self._log("decompose", json.dumps(dec))
        print("[CEO] Decomposed idea into agent focus areas (LLM).")

        max_spec_rounds = int(os.environ.get("MAX_PRODUCT_REVISIONS", "4"))
        spec: dict[str, Any] | None = None
        last_spec_review: dict[str, Any] | None = None

        for round_i in range(max_spec_rounds):
            if round_i == 0:
                self._send(
                    to_agent="product",
                    message_type="task",
                    payload={"idea": idea, "focus": dec["product_focus"], "revision_feedback": None},
                )
            else:
                fb = (
                    (last_spec_review or {}).get("feedback", "")
                    or "Improve specificity of personas, features, and user stories."
                )
                self._send(
                    to_agent="product",
                    message_type="revision_request",
                    payload={"idea": idea, "feedback": fb},
                )

            product_agent.process_inbox(bus)
            spec = None
            for m in bus.receive_all("ceo"):
                if m.get("from_agent") == "product" and m.get("message_type") == "result":
                    spec = m["payload"].get("product_spec")
            if not spec:
                raise RuntimeError("Product agent did not return product_spec")

            last_spec_review = review_product_spec(idea, spec)
            self._log(
                f"review_product_spec_round_{round_i}",
                json.dumps(
                    {"acceptable": last_spec_review["acceptable"], "reason": last_spec_review["reason"]}
                ),
            )
            print(
                f"[CEO] Product spec review (LLM): acceptable={last_spec_review['acceptable']} — "
                f"{last_spec_review['reason'][:120]}..."
            )
            if last_spec_review["acceptable"]:
                break
            if round_i == max_spec_rounds - 1:
                self._log("product_spec_forced_accept", "max rounds reached")
                print("[CEO] Max product revision rounds reached; proceeding.")
                break

        assert spec is not None

        max_eng = int(os.environ.get("MAX_ENGINEER_REVISIONS", "3"))
        qa_notes = ""
        marketing_copy: dict[str, Any] | None = None

        for eng_round in range(max_eng):
            if eng_round == 0:
                self._send(
                    to_agent="engineer",
                    message_type="task",
                    payload={"product_spec": spec, "idea": idea},
                )
            else:
                self._send(
                    to_agent="engineer",
                    message_type="revision_request",
                    payload={"product_spec": spec, "revision_notes": qa_notes},
                )

            engineer_process(bus)
            engineer_payload: dict[str, Any] | None = None
            for m in bus.receive_all("ceo"):
                if m.get("from_agent") == "engineer" and m.get("message_type") == "result":
                    engineer_payload = m["payload"]
            if not engineer_payload:
                raise RuntimeError("Engineer agent did not return result")

            pr_url = str(engineer_payload["pr_url"])
            html = str(engineer_payload["html"])
            pr_number = int(engineer_payload["pr_number"])
            head_sha = str(engineer_payload["head_sha"])
            landing_path = str(engineer_payload.get("landing_path", "index.html"))

            if marketing_copy is None:
                self._send(
                    to_agent="marketing",
                    message_type="task",
                    payload={"product_spec": spec, "pr_url": pr_url, "focus": dec["marketing_focus"]},
                )
                marketing_agent.process_inbox(bus)
                for m in bus.receive_all("ceo"):
                    if m.get("from_agent") == "marketing" and m.get("message_type") == "result":
                        marketing_copy = m["payload"].get("marketing_copy")
                if not marketing_copy:
                    raise RuntimeError("Marketing agent did not return copy")

            qa_result: dict[str, Any] | None = None
            if os.environ.get("ENABLE_QA", "true").lower() not in ("0", "false", "no"):
                self._send(
                    to_agent="qa",
                    message_type="task",
                    payload={
                        "html": html,
                        "marketing_copy": marketing_copy,
                        "product_spec": spec,
                        "pr_url": pr_url,
                        "pr_number": pr_number,
                        "head_sha": head_sha,
                        "landing_path": landing_path,
                    },
                )
                qa_agent.process_inbox(bus)
                for m in bus.receive_all("ceo"):
                    if m.get("from_agent") == "qa" and m.get("message_type") == "result":
                        qa_result = m["payload"]
                if qa_result:
                    self._log("qa_verdict", json.dumps(qa_result))
                    print(f"[CEO] QA verdict: {qa_result.get('verdict')} issues={qa_result.get('issues')}")

                if qa_result and qa_result.get("verdict") == "fail" and eng_round < max_eng - 1:
                    qa_notes = "\n".join(qa_result.get("issues") or [])
                    self._log("qa_fail_retry_engineer", qa_notes[:500])
                    print("[CEO] QA requested revisions; re-running Engineer (dynamic loop).")
                    continue

            summary_text = final_summary_llm(idea, spec, pr_url, marketing_copy)
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": "CEO final summary", "emoji": True}},
                {"type": "section", "text": {"type": "mrkdwn", "text": summary_text}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*PR:* <{pr_url}|View pull request>"}},
            ]
            _slack_post_blocks(blocks)
            self._log("final_slack_summary", "posted")

            return {
                "product_spec": spec,
                "pr_url": pr_url,
                "issue_url": engineer_payload.get("issue_url"),
                "marketing_copy": marketing_copy,
                "qa": qa_result,
                "decision_log": self.decision_log,
            }

        raise RuntimeError("Engineer/Marketing pipeline exhausted retries")
