"""
Sales-order Event Broker and downstream topic brokers.

Every published message is:
  1. Enriched with a sales_order_id (= originating transaction_id) so any
     downstream consumer can reconcile back to the initial sales order.
  2. Persisted as a JSON file via lib.event_store before fan-out to subscribers.

Topics
──────
SALES_ORDER_EVENT   simulation loop → risk factories + order validation
RT_RISK_1_OUTCOME   VAT-ratio factory    → RT consolidation factory
RT_RISK_2_OUTCOME   watchlist factory    → RT consolidation factory
RT_SCORE            consolidation        → release factory
ORDER_VALIDATION    order validation     → release factory
RELEASE_EVENT       release factory      → DB store worker
"""
from __future__ import annotations

import asyncio
from collections import defaultdict


def _inject_sales_order_id(message: dict) -> None:
    """
    Ensure every message carries sales_order_id at the top level.
    Derived from the first available source in priority order:
      existing sales_order_id
      → top-level transaction_id / orderIdentifier (new schema)
      → HouseConsignment.Order.orderIdentifier (arrival notification)
      → tx.sales_order_id / tx.transaction_id / tx.orderIdentifier
    Mutates the dict in-place so the field propagates to all subscribers.
    """
    if message.get("sales_order_id"):
        return
    soid = (
        message.get("transaction_id")
        or message.get("orderIdentifier")
        or ((message.get("HouseConsignment") or {}).get("Order") or {}).get("orderIdentifier")
        or (message.get("tx") or {}).get("sales_order_id")
        or (message.get("tx") or {}).get("transaction_id")
        or (message.get("tx") or {}).get("orderIdentifier")
    )
    if soid:
        message["sales_order_id"] = soid


class MessageBroker:
    """
    Simple fan-out broker.  Each call to subscribe() returns an independent
    asyncio.Queue so every subscriber receives every message on that topic.

    Before delivering, every message is:
      • enriched with sales_order_id (reconciliation key)
      • written to data/events/<topic>/ as a JSON file
    """

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = defaultdict(list)

    # ── Subscription management ───────────────────────────────────────────────

    def subscribe(self, topic: str, maxsize: int = 500) -> asyncio.Queue:
        """Register as a subscriber for *topic*; returns a dedicated queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._queues[topic].append(q)
        return q

    def unsubscribe(self, topic: str, q: asyncio.Queue) -> None:
        try:
            self._queues[topic].remove(q)
        except ValueError:
            pass

    # ── Publishing ────────────────────────────────────────────────────────────

    async def publish(self, topic: str, message: dict) -> None:
        """
        Enrich → persist → fan-out.
        Delivers *message* to every subscriber queue for *topic*.
        """
        from lib.event_store import write_event
        _inject_sales_order_id(message)
        write_event(topic, message)
        for q in self._queues[topic]:
            await q.put(message)

    def publish_nowait(self, topic: str, message: dict) -> None:
        """Non-blocking publish; silently drops for any full subscriber queue."""
        from lib.event_store import write_event
        _inject_sales_order_id(message)
        write_event(topic, message)
        for q in self._queues[topic]:
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass

    # ── Introspection ─────────────────────────────────────────────────────────

    def subscriber_count(self, topic: str) -> int:
        return len(self._queues[topic])

    def qsize(self, topic: str) -> int:
        """Total pending messages across all subscriber queues for *topic*."""
        return sum(q.qsize() for q in self._queues[topic])


# ── Topic name constants ──────────────────────────────────────────────────────

SALES_ORDER_EVENT    = "sales_order_event"      # simulation → risk + validation + DB store
RT_RISK_OUTCOME      = "rt_risk_outcome"      # all risk engines → assessment factory
ORDER_VALIDATION     = "order_validation"     # validation factory → assessment factory
# Unified assessment outcome: single topic for all three routing decisions.
# Each event carries a "route" field: "release" / "retain" / "investigate".
ASSESSMENT_OUTCOME   = "assessment_outcome"   # assessment factory → DB store + C&T risk mgmt
# Investigation outcome: produced by the Custom & Tax Risk Management system.
INVESTIGATION_OUTCOME = "investigation_outcome"  # C&T risk mgmt → DB store
# Final terminal outcome — produced by the DB Store factory. One event per
# completed order, with a status field in:
#   "automated_release"  (ASSESSMENT_OUTCOME route=release)
#   "custom_release"     (INVESTIGATION_OUTCOME outcome=released)
#   "custom_retain"      (INVESTIGATION_OUTCOME outcome=retained)
CUSTOM_OUTCOME       = "custom_outcome"
# Legacy aliases — kept so event_store counters and pipeline stats still work.
RELEASE_OUTCOME      = "assessment_outcome"   # alias
RT_RISK_1_OUTCOME    = "rt_risk_1_outcome"
RT_RISK_2_OUTCOME    = "rt_risk_2_outcome"
RT_RISK_3_OUTCOME    = "rt_risk_3_outcome"   # Ireland-specific watchlist (engine 3)
RT_SCORE             = "rt_score"
RELEASE_EVENT        = "release_event"
RETAIN_EVENT         = "retain_event"
INVESTIGATE_EVENT    = "investigate_event"


# ── Singleton used across api.py and workers ─────────────────────────────────

broker = MessageBroker()
