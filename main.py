#!/usr/bin/env python3
"""LaunchMind MAS entry point: CEO orchestrates Product, Engineer, Marketing, QA."""
from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv

from agents.ceo_agent import CEOAgent
from message_bus import MessageBus


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="LaunchMind multi-agent startup runner")
    parser.add_argument(
        "idea",
        nargs="*",
        help="Startup idea text (or set STARTUP_IDEA in .env)",
    )
    args = parser.parse_args()
    idea = " ".join(args.idea).strip() if args.idea else ""
    if not idea:
        idea = (os.environ.get("STARTUP_IDEA") or "").strip()
    if not idea:
        print(
            "Error: provide a startup idea as CLI arguments or set STARTUP_IDEA in .env",
            file=sys.stderr,
        )
        return 1

    bus = MessageBus()
    print("=== LaunchMind ===")
    print(f"Startup idea: {idea[:500]}{'...' if len(idea) > 500 else ''}\n")

    ceo = CEOAgent(bus, idea)
    try:
        result = ceo.run()
    except Exception as exc:
        print(f"\n[FATAL] {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1

    print("\n=== Message bus history (all messages) ===")
    for m in bus.history():
        print(json.dumps(m, indent=2)[:2000])
        if len(json.dumps(m)) > 2000:
            print("  ... [truncated]")

    print("\n=== CEO decision log ===")
    print(json.dumps(result.get("decision_log", []), indent=2))

    print("\n=== Done ===")
    print(f"PR: {result.get('pr_url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
