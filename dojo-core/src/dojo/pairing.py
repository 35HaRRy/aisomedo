from __future__ import annotations

from datetime import datetime, timedelta

from dojo.adapters.clock import SystemClock
from dojo.adapters.secrets import RandomSecretGenerator, Sha256Hasher
from dojo.exceptions import (
    ClientNotFound,
    OrganizationInactive,
    OrganizationNotFound,
    OrganizationScopeRequired,
    PairingCodeConsumed,
    PairingCodeExpired,
    PairingCodeInvalid,
)
from dojo.model import (
    AuditEvent,
    Client,
    Organization,
    PairingCode,
    PairingCodeIssued,
    PairingResult,
)
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

    def _scope(self, organization_id: int | None = None) -> DojoPairing:
        organization_id = organization_id if organization_id is not None \
            else self._pairing.organization_id
        if organization_id is None:
            raise OrganizationScopeRequired("organization scope is required")
        if self._pairing.organization_id == organization_id:
            return self
        return DojoPairing(
            pairing=self._pairing.for_organization(organization_id),
            audit=self._audit.for_organization(organization_id), clock=self._clock,
            hasher=self._hasher, generator=self._generator,
        )

    def create_pairing_code(
        self, *, requester: str, organization_id: int | None = None,
    ) -> PairingCodeIssued:
        scope = self._scope(organization_id)
        with scope._pairing.organization_transaction():
            return scope._create_pairing_code(requester=requester)

    def _create_pairing_code(self, *, requester: str) -> PairingCodeIssued:
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

    def pending_code_organization(self, *, code: str) -> Organization | None:
        """Organization a still-usable code belongs to; never consumes the code."""
        found = self._pairing.find_code_by_hash(self._hasher.hash(code))
        if found is None or found.consumed_at is not None:
            return None
        if self._clock.now() > found.expires_at:
            return None
        organization = self._pairing.find_organization(found.organization_id)
        return organization if organization is not None and organization.active else None

    def validate_code(self, *, code: str, kind: str, name: str) -> PairingResult:
        found = self._pairing.find_code_by_hash(self._hasher.hash(code))
        if found is None:
            raise PairingCodeInvalid("invalid pairing code")
        try:
            scope = self._scope(found.organization_id)
            with scope._pairing.organization_transaction():
                return scope._validate_code(code=code, kind=kind, name=name)
        except (OrganizationInactive, OrganizationNotFound) as exc:
            raise PairingCodeInvalid("invalid pairing code") from exc

    def _validate_code(self, *, code: str, kind: str, name: str) -> PairingResult:
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

    def list_clients(self, *, organization_id: int | None = None) -> list[Client]:
        scope = self._scope(organization_id)
        with scope._pairing.organization_transaction():
            return scope._pairing.list_clients()

    def revoke_client(
        self, *, client_id: int, requester: str, organization_id: int | None = None,
    ) -> None:
        scope = self._scope(organization_id)
        with scope._pairing.organization_transaction():
            scope._revoke_client(client_id=client_id, requester=requester)

    def _revoke_client(self, *, client_id: int, requester: str) -> None:
        client = self._pairing.find_client_by_id(client_id)
        if client is None:
            raise ClientNotFound(f"no client {client_id}")
        if client.revoked_at is not None:
            return
        now = self._clock.now()
        self._pairing.mark_client_revoked(client_id, now)
        self._audit.append(
            AuditEvent(
                action="pairing.client_revoked",
                actor=requester,
                occurred_at=now,
                details={"client_id": client_id, "name": client.name, "kind": client.kind},
            )
        )

    def authenticate_bearer(self, token: str) -> Client | None:
        return self._verify_credential(self._hasher.hash(token))

    def authenticate_session(self, session_id: str) -> Client | None:
        return self._verify_credential(self._hasher.hash(session_id))

    def authorization_deadline(self, client: Client) -> datetime | None:
        """Deadline for this authentication; no credential leaves the facade."""
        return self._clock.now() + IDLE_TTL if client.kind == "browser" else None

    def _verify_credential(self, credential_hash: str) -> Client | None:
        now = self._clock.now()
        client = self._pairing.find_client_by_credential_hash(credential_hash)
        if client is None or client.revoked_at is not None:
            return None
        if client.kind == "browser":
            last = client.last_seen_at
            if last is None or (now - last) > IDLE_TTL:
                return None
        try:
            scope = self._scope(client.organization_id)
            with scope._pairing.organization_transaction():
                scope._pairing.touch_client(client.id, now)
        except (OrganizationInactive, OrganizationNotFound):
            return None
        return client
