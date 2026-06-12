"""Append-only audit trail.

Every stage transition, exception, retry, escalation, and human decision emits
exactly one :class:`AuditEvent`. The trail is append-only: there is no update or
delete API. This satisfies the AIOS append-only-audit invariant and gives the
judges a concrete, replayable execution history per case.

The trail is process-local (used by the demo, tests, eval, and webapp). The
Maestro adapter (:mod:`command_tower.maestro_adapter`) is what persists these to
the Automation Cloud data store in the production path.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from .models import AuditEvent, new_id, now_iso


class AuditTrail:
    """An append-only list of audit events, queryable by case/stage/actor."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    # ---- the ONLY mutation entry point -----------------------------------
    def emit(self, *, case_id: str, stage: int, actor: str, action: str,
             detail: str = "", evidence_refs: Iterable[str] | None = None) -> AuditEvent:
        ev = AuditEvent(
            event_id=new_id("ae"),
            case_id=case_id,
            stage=stage,
            actor=actor,
            action=action,
            detail=detail,
            ts=now_iso(),
            evidence_refs=list(evidence_refs or []),
        )
        self._events.append(ev)
        return ev

    # ---- read-only views --------------------------------------------------
    @property
    def events(self) -> list[AuditEvent]:
        # return a copy so callers cannot splice the internal log
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def for_case(self, case_id: str) -> list[AuditEvent]:
        return [e for e in self._events if e.case_id == case_id]

    def by_actor(self, actor: str) -> list[AuditEvent]:
        return [e for e in self._events if e.actor == actor]

    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._events]

    def write(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"schema": "command_tower_audit/1.0",
                       "count": len(self._events),
                       "events": self.to_list()}, fh, indent=2, ensure_ascii=False)
