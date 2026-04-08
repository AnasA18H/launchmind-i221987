"""Product agent: startup idea -> structured product specification JSON."""
from __future__ import annotations

from typing import Any

from agents.utils import iso_timestamp, new_message_id
from llm import call_llm, parse_json_from_llm
from message_bus import MessageBus
from schemas import make_message


def _system_prompt() -> str:
    return """You are an expert product manager. Output only valid JSON matching the schema.
The JSON must have:
- value_proposition: string, one sentence
- personas: array of {name, role, pain_point} (2 or 3 items)
- features: array of {name, description, priority} exactly 5 items, priority 1=highest through 5
- user_stories: array of exactly 3 strings, each in format "As a [user], I want to [action] so that [benefit]"
No markdown, no explanation outside JSON."""


def _normalize_spec(raw: dict[str, Any]) -> dict[str, Any]:
    vp = raw.get("value_proposition", "").strip()
    personas = raw.get("personas") or []
    features = raw.get("features") or []
    stories = raw.get("user_stories") or []
    out = {
        "value_proposition": vp,
        "personas": [],
        "features": [],
        "user_stories": [],
    }
    for p in personas[:5]:
        if isinstance(p, dict):
            out["personas"].append(
                {
                    "name": str(p.get("name", "User")),
                    "role": str(p.get("role", "")),
                    "pain_point": str(p.get("pain_point", "")),
                }
            )
    while len(out["personas"]) < 2:
        out["personas"].append({"name": "User", "role": "Early adopter", "pain_point": "Needs clarity"})
    for f in features[:10]:
        if isinstance(f, dict):
            pr = f.get("priority", 99)
            try:
                pr = int(pr)
            except (TypeError, ValueError):
                pr = 99
            out["features"].append(
                {
                    "name": str(f.get("name", "Feature")),
                    "description": str(f.get("description", "")),
                    "priority": pr,
                }
            )
    out["features"].sort(key=lambda x: x["priority"])
    out["features"] = out["features"][:5]
    while len(out["features"]) < 5:
        out["features"].append(
            {"name": f"Feature {len(out['features']) + 1}", "description": "TBD", "priority": len(out["features"]) + 1}
        )
    for s in stories[:5]:
        if isinstance(s, str) and s.strip():
            out["user_stories"].append(s.strip())
    while len(out["user_stories"]) < 3:
        out["user_stories"].append(
            "As a user, I want to accomplish my goal so that I save time."
        )
    out["user_stories"] = out["user_stories"][:3]
    return out


def generate_spec(idea: str, revision_feedback: str | None = None) -> dict[str, Any]:
    user = f"Startup idea:\n{idea}\n"
    if revision_feedback:
        user += f"\nRevision feedback from CEO (address this explicitly):\n{revision_feedback}\n"
    user += "\nReturn the product specification JSON only."
    text = call_llm(_system_prompt(), user, max_tokens=2048)
    raw = parse_json_from_llm(text)
    if not isinstance(raw, dict):
        raise ValueError("LLM did not return a JSON object for product spec")
    return _normalize_spec(raw)


def process_inbox(bus: MessageBus) -> None:
    """Drain messages addressed to product; reply to ceo with result or confirmation."""
    for msg in bus.receive_all("product"):
        mtype = msg["message_type"]
        payload = msg["payload"]
        idea = payload.get("idea", "")
        parent = msg.get("message_id")
        if mtype == "task":
            feedback = payload.get("revision_feedback")
            spec = generate_spec(idea, feedback if isinstance(feedback, str) else None)
            bus.send(
                make_message(
                    message_id=new_message_id(),
                    from_agent="product",
                    to_agent="ceo",
                    message_type="result",
                    payload={"product_spec": spec, "idea": idea},
                    timestamp=iso_timestamp(),
                    parent_message_id=parent,
                )
            )
            bus.send(
                make_message(
                    message_id=new_message_id(),
                    from_agent="product",
                    to_agent="ceo",
                    message_type="confirmation",
                    payload={"status": "product_spec_ready", "summary": spec["value_proposition"][:200]},
                    timestamp=iso_timestamp(),
                    parent_message_id=parent,
                )
            )
        elif mtype == "revision_request":
            feedback = payload.get("feedback", "")
            spec = generate_spec(idea, str(feedback))
            bus.send(
                make_message(
                    message_id=new_message_id(),
                    from_agent="product",
                    to_agent="ceo",
                    message_type="result",
                    payload={"product_spec": spec, "idea": idea},
                    timestamp=iso_timestamp(),
                    parent_message_id=parent,
                )
            )
            bus.send(
                make_message(
                    message_id=new_message_id(),
                    from_agent="product",
                    to_agent="ceo",
                    message_type="confirmation",
                    payload={"status": "revised_product_spec_ready"},
                    timestamp=iso_timestamp(),
                    parent_message_id=parent,
                )
            )
