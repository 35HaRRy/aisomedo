from __future__ import annotations

from typing import cast

from dojo.adapters.clock import SystemClock
from dojo.exceptions import ConsentPolicyDowngrade, NoConsentPolicy
from dojo.model import (
    AuditEvent,
    Client,
    ConsentAcceptance,
    ConsentPolicy,
    SetupItem,
)
from dojo.ports import AuditStore, Clock, PairingStore, SettingsStore, SetupStore

PAIRING_ITEM = "pairing"
CONSENT_ITEM = "consent"
LOGO_ITEM = "logo"
CAPTION_TEMPLATE_ITEM = "caption_template"


class DojoSetup:
    """Deep behavioral seam for first-run onboarding and media-consent policy.

    Owns the installation-wide consent-policy lifecycle, once-per-version
    acceptance recording (inherited by every client), the derived onboarding
    checklist, and the ``is_ready`` scheduling gate. FastAPI routes and the
    worker scheduler share this facade.
    """

    def __init__(
        self,
        *,
        setup: SetupStore,
        audit: AuditStore,
        pairing: PairingStore,
        clock: Clock | None = None,
        settings: SettingsStore | None = None,
    ) -> None:
        self._setup = setup
        self._audit = audit
        self._pairing = pairing
        self._clock = clock or SystemClock()
        self._settings = settings or cast(SettingsStore, setup)

    def current_policy(self) -> ConsentPolicy | None:
        """Return the current (highest-version) consent policy, if any."""
        return self._setup.get_current_policy()

    def set_policy(self, *, version: int, text: str, requester: str) -> ConsentPolicy:
        """Create or replace a policy version; reject downgrades; audit."""
        current = self._setup.get_current_policy()
        if current is not None and version < current.version:
            raise ConsentPolicyDowngrade(
                f"cannot set version {version}; current is {current.version}"
            )
        now = self._clock.now()
        policy = self._setup.create_policy(
            version=version, text=text, created_by=requester, created_at=now
        )
        self._audit.append(
            AuditEvent(
                action="consent.policy_updated",
                actor=requester,
                occurred_at=now,
                details={"version": version},
            )
        )
        return policy

    def current_acceptance(self) -> ConsentAcceptance | None:
        """Return the acceptance for the current policy version, if any."""
        policy = self._setup.get_current_policy()
        if policy is None:
            return None
        return self._setup.find_acceptance(policy.version)

    def accept_current_policy(self, *, client: Client) -> ConsentAcceptance:
        """Accept the current policy version, once per version, idempotently."""
        policy = self._setup.get_current_policy()
        if policy is None:
            raise NoConsentPolicy("no consent policy configured")
        existing = self._setup.find_acceptance(policy.version)
        if existing is not None:
            return existing
        now = self._clock.now()
        acceptance = ConsentAcceptance(
            policy_version=policy.version,
            accepted_at=now,
            accepting_client_id=client.id,
            accepting_client_name=client.name,
            accepting_client_kind=client.kind,
        )
        if self._setup.record_acceptance(acceptance):
            self._audit.append(
                AuditEvent(
                    action="consent.accepted",
                    actor=str(client.id),
                    occurred_at=now,
                    details={"version": policy.version},
                )
            )
            recorded = self._setup.find_acceptance(policy.version)
            if recorded is None:
                raise NoConsentPolicy("consent acceptance lost")
            return recorded
        raced = self._setup.find_acceptance(policy.version)
        if raced is None:
            raise NoConsentPolicy("consent acceptance lost")
        return raced

    def checklist(self) -> list[SetupItem]:
        """Derive the onboarding checklist from real state."""
        policy = self._setup.get_current_policy()
        consent_done = (
            policy is not None and self._setup.find_acceptance(policy.version) is not None
        )
        pairing_done = any(c.revoked_at is None for c in self._pairing.list_clients())
        logo_done = self._settings.get("branding.logo_asset") is not None
        caption_done = self._settings.get("branding.caption_template") is not None
        return [
            SetupItem(key=PAIRING_ITEM, label="Pairing", complete=pairing_done),
            SetupItem(key=CONSENT_ITEM, label="Media consent", complete=consent_done),
            SetupItem(key=LOGO_ITEM, label="Dojo logo", complete=logo_done),
            SetupItem(
                key=CAPTION_TEMPLATE_ITEM,
                label="Caption template",
                complete=caption_done,
            ),
        ]

    def checklist_item(self, key: str) -> SetupItem:
        return next(item for item in self.checklist() if item.key == key)

    def is_ready(self) -> bool:
        """True when every onboarding checklist item is complete."""
        return all(item.complete for item in self.checklist())
