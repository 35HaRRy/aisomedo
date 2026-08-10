from __future__ import annotations

from datetime import timedelta

from dojo.adapters.clock import SystemClock
from dojo.adapters.secrets import RandomSecretGenerator, Sha256Hasher
from dojo.exceptions import (
    PairingCodeConsumed,
    PairingCodeExpired,
    PairingCodeInvalid,
)
from dojo.model import AuditEvent, Client, PairingCode, PairingCodeIssued, PairingResult
from dojo.ports import AuditStore, Clock, Hasher, PairingStore, SecretGenerator

CODE_TTL = timedelta(minutes=10)
IDLE_TTL = timedelta(days=30)
SUPPORTED_KINDS = ("device", "browser")


class DojoPairing:
    """Deep behavioral seam for accountless pairing and equal-privilege auth.

    Owns pairing-code issuance, single-use validation, client listing and
    revocation, and credential verification. FastAPI guards routes through
    this facade; only the wall clock, hashing, and secret generation are
    swappable adapters.
    """

    def __init__(
        self,
        *,
        pairing: PairingStore,
        audit: AuditStore,
        clock: Clock | None = None,
        hasher: Hasher | None = None,
        generator: SecretGenerator | None = None,
    ) -> None:
        self._pairing = pairing
        self._audit = audit
        self._clock = clock or SystemClock()
        self._hasher = hasher or Sha256Hasher()
        self._generator = generator or RandomSecretGenerator()

    def create_pairing_code(self, *, requester: str) -> PairingCodeIssued:
        raw = self._generator.generate_code()
        now = self._clock.now()
        code = self._pairing.create_code(
            PairingCode(
                id=0,
                code_hash=self._hasher.hash(raw),
                expires_at=now + CODE_TTL,
                created_by=requester,
                created_at=now,
            )
        )
        self._audit.append(
            AuditEvent(
                action="pairing.code_created",
                actor=requester,
                occurred_at=now,
                details={"code_id": code.id, "ttl_seconds": int(CODE_TTL.total_seconds())},
            )
        )
        return PairingCodeIssued(raw_code=raw, expires_at=code.expires_at)

    def validate_code(self, *, code: str, kind: str, name: str) -> PairingResult:
        if kind not in SUPPORTED_KINDS:
            raise ValueError(f"unsupported client kind: {kind}")
        now = self._clock.now()
        found = self._pairing.find_code_by_hash(self._hasher.hash(code))
        if found is None:
            raise PairingCodeInvalid("invalid pairing code")
        if found.consumed_at is not None:
            raise PairingCodeConsumed("pairing code already used")
        if now > found.expires_at:
            raise PairingCodeExpired("pairing code expired")
        if not self._pairing.mark_code_consumed(found.id, now):
            raise PairingCodeConsumed("pairing code already used")

        raw_credential = self._generator.generate_token()
        client = self._pairing.create_client(
            Client(
                id=0,
                name=name,
                kind=kind,
                created_at=now,
                created_by=found.created_by,
                last_seen_at=now,
            ),
            credential_hash=self._hasher.hash(raw_credential),
        )
        self._audit.append(
            AuditEvent(
                action="pairing.client_paired",
                actor=found.created_by,
                occurred_at=now,
                details={"client_id": client.id, "name": name, "kind": kind},
            )
        )
        return PairingResult(client_id=client.id, kind=kind, raw_credential=raw_credential)

    def authenticate_bearer(self, token: str) -> Client | None:
        return self._verify_credential(self._hasher.hash(token))

    def authenticate_session(self, session_id: str) -> Client | None:
        return self._verify_credential(self._hasher.hash(session_id))

    def _verify_credential(self, credential_hash: str) -> Client | None:
        now = self._clock.now()
        client = self._pairing.find_client_by_credential_hash(credential_hash)
        if client is None or client.revoked_at is not None:
            return None
        if client.kind == "browser":
            last = client.last_seen_at
            if last is None or (now - last) > IDLE_TTL:
                return None
        self._pairing.touch_client(client.id, now)
        return client
