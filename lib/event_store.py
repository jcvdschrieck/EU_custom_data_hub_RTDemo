"""
Event Store — persists every broker message as an individual JSON file.

Directory layout
────────────────
data/events/
  sales_order_event/
    20260308T142301123456_<tx_id[:12]>.json
  rt_risk_1_outcome/
    ...
  rt_risk_2_outcome/
  rt_score/
  order_validation/
  release_event/

Each file is the full message payload wrapped in an _event_meta envelope:
  {
    "_event_meta": {
      "event_id":       "<uuid4>",
      "topic":          "<topic name>",
      "published_at":   "<ISO timestamp>",
      "sales_order_id": "<original transaction_id for reconciliation>"
    },
    ... message fields ...
  }

Flushing
────────
Call flush_events() to delete all event files (done at simulation
start/reset so every run starts with a clean slate).
"""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

EVENTS_DIR = Path(__file__).parent.parent / "data" / "events"


def _topic_dir(topic: str) -> Path:
    d = EVENTS_DIR / topic
    d.mkdir(parents=True, exist_ok=True)
    return d


def _extract_sales_order_id(message: dict) -> str:
    """Walk the message to find the originating transaction_id."""
    return (
        message.get("sales_order_id")
        or message.get("transaction_id")
        or (message.get("tx") or {}).get("sales_order_id")
        or (message.get("tx") or {}).get("transaction_id")
        or "unknown"
    )


def write_event(topic: str, message: dict) -> None:
    """
    Persist *message* as a JSON file under data/events/<topic>/.
    The file includes a _event_meta envelope with reconciliation fields.
    Runs synchronously — acceptable given the 120 ms simulation pacing.
    """
    sales_order_id = _extract_sales_order_id(message)
    ts = datetime.now(timezone.utc)
    filename = (
        f"{ts.strftime('%Y%m%dT%H%M%S%f')}"
        f"_{sales_order_id[:12]}.json"
    )
    envelope = {
        "_event_meta": {
            "event_id":       str(uuid.uuid4()),
            "topic":          topic,
            "published_at":   ts.isoformat(),
            "sales_order_id": sales_order_id,
        },
        **message,
    }
    path = _topic_dir(topic) / filename
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(envelope, fh, indent=2, default=str)


def flush_events() -> None:
    """
    Delete all persisted event files.
    Called at simulation start and reset to ensure a clean slate.
    """
    if EVENTS_DIR.exists():
        shutil.rmtree(EVENTS_DIR)
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)


def event_count(topic: str | None = None) -> int:
    """Return total number of persisted event files, optionally filtered by topic."""
    if topic:
        d = EVENTS_DIR / topic
        return len(list(d.glob("*.json"))) if d.exists() else 0
    return sum(1 for _ in EVENTS_DIR.rglob("*.json")) if EVENTS_DIR.exists() else 0


def count_field_value(topic: str, field: str, value) -> int:
    """Count persisted events for *topic* where the top-level *field* equals *value*."""
    import json as _json
    d = EVENTS_DIR / topic
    if not d.exists():
        return 0
    n = 0
    for f in d.glob("*.json"):
        try:
            if _json.loads(f.read_text()).get(field) == value:
                n += 1
        except Exception:
            pass
    return n
