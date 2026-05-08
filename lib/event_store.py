"""
Event Store — persists every broker message as an individual JSON file.

Directory layout
────────────────
data/events/
  sales_order_event/
    <orderIdentifier>_sales_order_event.json
  rt_risk_1_outcome/
    <orderIdentifier>_rt_risk_1_outcome.json
  rt_risk_2_outcome/
  rt_score/
  order_validation/
  arrival_notification/
  release_event/

Each file is the clean, schema-conforming version of the message wrapped in
a _event_meta envelope:
  {
    "_event_meta": {
      "event_id":         "<uuid4>",
      "topic":            "<topic name>",
      "published_at":     "<ISO timestamp>",
      "order_identifier": "<orderIdentifier for reconciliation>"
    },
    ... clean message fields (no internal flat fields) ...
  }

Sales Order Event files follow simplified_order.json.
Arrival Notification files follow availability-notification_simplified.json.
All other topic files contain: {orderIdentifier, timestamp, messageTopic, outcome}.

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

# ── In-memory counters ─────────────────────────────────────────────────────────
# Maintained incrementally in write_event() and cleared in flush_events().
# Because flush_events() is called at every server startup the counters always
# start from zero, matching the freshly-emptied event directory.
#
# These replace the previous filesystem-scan + TTL-cache approach:
#   Old: event_count / count_field_value → O(n files) disk scan per call
#   New: O(1) dict lookup, updated once at write time
#
# Thread safety: CPython's GIL makes individual dict reads/writes atomic.
# The read-modify-write in _inc() is not atomic, but a rare ±1 counter
# discrepancy during concurrent writes is harmless for live UI counters.

_topic_counts: dict[str, int] = {}
_field_counts: dict[tuple, int] = {}  # (topic, dot.path, value) → count


def _inc(d: dict, key) -> None:
    d[key] = d.get(key, 0) + 1


def _extract_field_counts(topic: str, payload: dict) -> None:
    """Walk *payload* and increment _field_counts for every leaf value."""
    def _walk(obj: object, prefix: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                _walk(v, f"{prefix}.{k}" if prefix else k)
        elif prefix:
            _inc(_field_counts, (topic, prefix, obj))
    _walk(payload, "")


EVENTS_DIR = Path(__file__).parent.parent / "data" / "events"


def _topic_dir(topic: str) -> Path:
    d = EVENTS_DIR / topic
    d.mkdir(parents=True, exist_ok=True)
    return d


def _extract_order_identifier(file_payload: dict) -> str:
    """Extract the orderIdentifier from a clean file payload."""
    return (
        file_payload.get("orderIdentifier")
        or (file_payload.get("HouseConsignment") or {}).get("Order", {}).get("orderIdentifier")
        or file_payload.get("sales_order_id")
        or "unknown"
    )


def write_event(topic: str, message: dict) -> None:
    """
    Persist *message* as a JSON file under data/events/<topic>/.

    The file content is the clean, schema-conforming payload (internal
    flat fields stripped) wrapped in a _event_meta envelope.
    File name: <orderIdentifier>_<topic>.json
    """
    from lib.message_factory import build_file_payload

    file_payload     = build_file_payload(topic, message)
    order_identifier = _extract_order_identifier(file_payload)
    filename         = f"{order_identifier}_{topic}.json"

    ts = datetime.now(timezone.utc)
    envelope = {
        "_event_meta": {
            "event_id":         str(uuid.uuid4()),
            "topic":            topic,
            "published_at":     ts.isoformat(),
            "order_identifier": order_identifier,
        },
        **file_payload,
    }
    path = _topic_dir(topic) / filename
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(envelope, fh, indent=2, default=str)

    # Update in-memory counters so callers never need to re-scan the directory.
    _inc(_topic_counts, topic)
    _extract_field_counts(topic, file_payload)


def flush_events() -> None:
    """
    Delete all persisted event files and reset in-memory counters.
    Called at simulation start and reset to ensure a clean slate.

    Uses ignore_errors=True because background workers may still be writing
    events to disk while reset is in progress (esp. after a fast ×100 run);
    any orphan files left behind will be overwritten on the next start.
    """
    _topic_counts.clear()
    _field_counts.clear()
    if EVENTS_DIR.exists():
        shutil.rmtree(EVENTS_DIR, ignore_errors=True)
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)


def event_count(topic: str | None = None) -> int:
    """Return total number of persisted event files, optionally filtered by topic."""
    if topic:
        return _topic_counts.get(topic, 0)
    return sum(_topic_counts.values())


def get_events_for_order(order_identifier: str) -> list[dict]:
    """
    Return every persisted event whose filename starts with *order_identifier*,
    across every topic directory under data/events/. Each event is the parsed
    file content (envelope with _event_meta + clean payload), and the result
    is sorted chronologically by _event_meta.published_at.

    Used by GET /api/transactions/{tx_id}/timeline so the manual investigation
    UI can display the full processing history of a single transaction.
    """
    if not EVENTS_DIR.exists() or not order_identifier:
        return []
    out: list[dict] = []
    # Each topic dir contains <orderIdentifier>_<topic>.json files. Glob the
    # specific prefix instead of reading every file.
    for topic_dir in EVENTS_DIR.iterdir():
        if not topic_dir.is_dir():
            continue
        for f in topic_dir.glob(f"{order_identifier}_*.json"):
            try:
                out.append(json.loads(f.read_text()))
            except Exception:
                pass
    out.sort(key=lambda e: ((e.get("_event_meta") or {}).get("published_at") or ""))
    return out


def count_field_value(topic: str, field: str, value) -> int:
    """
    Count persisted events for *topic* where *field* equals *value*.

    *field* supports dot-notation for nested fields, e.g. "outcome.flagged"
    to reach {"outcome": {"flagged": true}}.
    """
    return _field_counts.get((topic, field, value), 0)
