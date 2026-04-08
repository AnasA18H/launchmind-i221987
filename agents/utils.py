from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def iso_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_message_id() -> str:
    return str(uuid4())
