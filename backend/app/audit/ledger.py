import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.models.schemas import AuditEvent


class AuditLedger:
    """Tamper-evident, hash-chained append-only event ledger.

    Provides verifiable provenance for every authorization decision,
    proposal generation, approval, policy check, and payment state transition.
    """

    def __init__(self):
        self._events: List[AuditEvent] = []
        self._latest_hash: str = "GENESIS_ROOT_HASH"

    def record_event(
        self,
        event_type: str,
        checkout_id: Optional[str] = None,
        policy_version: Optional[int] = None,
        proposal_fingerprint: Optional[str] = None,
        decision: Optional[str] = None,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
    ) -> AuditEvent:
        """Append a new verified event to the ledger with cryptographic back-link."""
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        now = timestamp or datetime.now(timezone.utc)
        meta = metadata or {}

        # Construct hash payload
        hash_payload = {
            "prev_event_hash": self._latest_hash,
            "event_id": event_id,
            "timestamp": now.isoformat(),
            "event_type": event_type,
            "checkout_id": checkout_id,
            "policy_version": policy_version,
            "proposal_fingerprint": proposal_fingerprint,
            "decision": decision,
            "reason": reason,
            "metadata": meta,
        }
        serialized = json.dumps(hash_payload, sort_keys=True, default=str)
        event_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

        event = AuditEvent(
            event_id=event_id,
            timestamp=now,
            event_type=event_type,
            checkout_id=checkout_id,
            policy_version=policy_version,
            proposal_fingerprint=proposal_fingerprint,
            decision=decision,
            reason=reason,
            metadata=meta,
            prev_event_hash=self._latest_hash,
            event_hash=event_hash,
        )

        self._events.append(event)
        self._latest_hash = event_hash
        return event

    def get_events(
        self,
        checkout_id: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> List[AuditEvent]:
        """Query events with optional filtering."""
        filtered = self._events
        if checkout_id:
            filtered = [e for e in filtered if e.checkout_id == checkout_id]
        if event_type:
            filtered = [e for e in filtered if e.event_type == event_type]
        return list(filtered)

    def verify_ledger_integrity(self) -> bool:
        """Verify complete cryptographic chain of the ledger.

        Returns False if any event was tampered with, deleted, or reordered.
        """
        expected_prev_hash = "GENESIS_ROOT_HASH"
        for event in self._events:
            if event.prev_event_hash != expected_prev_hash:
                return False
            hash_payload = {
                "prev_event_hash": event.prev_event_hash,
                "event_id": event.event_id,
                "timestamp": event.timestamp.isoformat(),
                "event_type": event.event_type,
                "checkout_id": event.checkout_id,
                "policy_version": event.policy_version,
                "proposal_fingerprint": event.proposal_fingerprint,
                "decision": event.decision,
                "reason": event.reason,
                "metadata": event.metadata,
            }
            serialized = json.dumps(hash_payload, sort_keys=True, default=str)
            computed_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            if not hmac.compare_digest(computed_hash, event.event_hash):
                return False
            expected_prev_hash = event.event_hash
        return True
