"""Append-only audit events for decisions and executions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import uuid
from typing import Any, Protocol

from .models import utc_now


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    payload: dict[str, Any]
    timestamp: datetime = field(default_factory=utc_now)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def as_json(self) -> str:
        return json.dumps(self.payload, default=str, sort_keys=True)


class AuditTrail(Protocol):
    def append(self, event: AuditEvent) -> None: ...


class InMemoryAuditTrail:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


def record(audit: AuditTrail | None, event_type: str, payload: dict[str, Any]) -> AuditEvent:
    event = AuditEvent(event_type, payload)
    if audit is not None:
        audit.append(event)
    return event

