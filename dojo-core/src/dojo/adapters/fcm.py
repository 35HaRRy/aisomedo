"""Firebase Cloud Messaging transport for the notifier seam.

The SDK is imported lazily so a deployment that never enables FCM does not
need ``firebase_admin`` installed, while the worker image always has it.

Nothing here reports a send that was not attempted and confirmed: a missing
SDK method, an unrecognised response shape or a truncated batch all become
retries, and only a proven unregistered token is ever reported invalid.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from dojo.model import Notification, NotificationResult

logger = logging.getLogger(__name__)

#: ``messaging.send_each_for_multicast`` refuses more than 500 messages per
#: call, so larger recipient sets are chunked at the documented limit.
MULTICAST_TOKEN_LIMIT = 500

#: Bound on a single provider request. A hung provider must not stall a
#: delivery loop that caps its own wall-clock budget on top of this.
FCM_HTTP_TIMEOUT_SECONDS = 10

#: Named application, so a process that builds more than one notifier reuses
#: one credential and HTTP client instead of initializing the SDK twice.
FCM_APP_NAME = "dojo-fcm"

#: Operational alerts carry the durable alert id in ``data``. Android uses it
#: as the notification tag, so a redelivery replaces the first notification
#: instead of stacking a duplicate. Other message types have no tag.
ALERT_TAG_DATA_KEY = "alert_id"

#: Only a proven unregistered token may delete a registration. A generic
#: ``invalid-argument`` is at least as likely to be a rejected payload, and
#: deleting a live registration would silently stop delivery for that device
#: until it registered again. ``not-found`` is the HTTP-mapped code the SDK
#: uses for ``UnregisteredError``; the class name keeps the check correct if
#: that mapping ever changes.
INVALID_TOKEN_CODES = frozenset({"not-found"})
INVALID_TOKEN_ERROR_NAMES = frozenset({"UnregisteredError"})


def _import(module: str) -> Any:
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise RuntimeError(
            f"{module} is required for FCM delivery; install Firebase Admin or disable FCM"
        ) from exc


def _is_invalid_token(error: object) -> bool:
    """True only for an error that proves the token itself is unusable."""
    if error is None:
        return False
    if getattr(error, "code", None) in INVALID_TOKEN_CODES:
        return True
    return type(error).__name__ in INVALID_TOKEN_ERROR_NAMES


def _ensure_app(admin: Any, *, app_name: str, project_id: str | None, timeout_seconds: int) -> Any:
    """Reuse the named SDK app, or initialize one from default credentials.

    Credentials and project identity are resolved here, at construction, so a
    deployment that enabled FCM without usable credentials fails at startup
    instead of at the first alert.
    """
    try:
        return admin.get_app(app_name)
    except ValueError:  # not initialized yet; the named app is created below
        pass
    options: dict[str, Any] = {"httpTimeout": timeout_seconds}
    if project_id:
        # Without a project id the SDK can still read one from the
        # credential or GOOGLE_CLOUD_PROJECT, so this stays optional.
        options["projectId"] = project_id
    try:
        return admin.initialize_app(
            admin.credentials.ApplicationDefault(), options, name=app_name
        )
    except Exception as exc:  # noqa: BLE001 - reported as a configuration failure
        raise RuntimeError(
            "FCM is enabled but Firebase could not be configured: project identity and "
            "Application Default Credentials are both required"
        ) from exc


class FcmNotifier:
    """Batch notifier backed by ``firebase_admin.messaging``.

    ``messaging``, ``app`` and ``admin`` are injection points for unit tests,
    which pass the SDK's own message types and a fake sender. Production
    passes none of them and gets a real, credential-resolved app.
    """

    def __init__(
        self,
        messaging: Any | None = None,
        *,
        app: Any | None = None,
        admin: Any | None = None,
        project_id: str | None = None,
        timeout_seconds: int = FCM_HTTP_TIMEOUT_SECONDS,
        app_name: str = FCM_APP_NAME,
    ) -> None:
        self._messaging = (
            messaging if messaging is not None else _import("firebase_admin.messaging")
        )
        self._app = app if app is not None else _ensure_app(
            admin if admin is not None else _import("firebase_admin"),
            app_name=app_name,
            project_id=project_id,
            timeout_seconds=timeout_seconds,
        )

    def send(self, notification: Notification, tokens: list[str]) -> NotificationResult:
        if not tokens:
            return NotificationResult(delivered=[], invalid_tokens=[], transient_failures=[])
        delivered: list[str] = []
        invalid: list[str] = []
        transient: list[str] = []
        for start in range(0, len(tokens), MULTICAST_TOKEN_LIMIT):
            chunk = list(tokens[start:start + MULTICAST_TOKEN_LIMIT])
            result = self._send_chunk(notification, chunk)
            delivered.extend(result.delivered)
            invalid.extend(result.invalid_tokens)
            transient.extend(result.transient_failures)
        return NotificationResult(
            delivered=delivered, invalid_tokens=invalid, transient_failures=transient
        )

    def _send_chunk(self, notification: Notification, tokens: list[str]) -> NotificationResult:
        send = getattr(self._messaging, "send_each_for_multicast", None)
        if send is None:
            raise RuntimeError(
                "firebase_admin.messaging has no send_each_for_multicast; refusing to "
                "report a send that was never attempted"
            )
        return self._parse_response(send(self._build(notification, tokens), app=self._app), tokens)

    def _build(self, notification: Notification, tokens: list[str]) -> Any:
        # ``tokens`` is deprecated in favour of Firebase installation IDs
        # (``fids``), but a registration token is what the Android client
        # stores and reports through the push registration store, so the
        # supported-but-deprecated field is the only correct one here.
        return self._messaging.MulticastMessage(
            notification=self._messaging.Notification(
                title=notification.title, body=notification.body
            ),
            android=self._android_config(notification),
            # FCM rejects non-string data values, so they are normalized here
            # instead of failing a whole batch at the provider.
            data={str(key): str(value) for key, value in notification.data.items()},
            tokens=tokens,
        )

    def _android_config(self, notification: Notification) -> Any | None:
        tag = notification.data.get(ALERT_TAG_DATA_KEY)
        if not tag:
            return None
        return self._messaging.AndroidConfig(
            notification=self._messaging.AndroidNotification(tag=str(tag))
        )

    def _parse_response(self, response: Any, tokens: list[str]) -> NotificationResult:
        responses = getattr(response, "responses", None)
        if not isinstance(responses, (list, tuple)):
            # An unrecognised shape cannot prove acceptance for anyone, so the
            # whole chunk is retried instead of being counted as delivered.
            logger.warning(
                "FCM response shape unrecognised; retrying every token in the batch",
                extra={"event": "fcm.response_shape_unknown", "status": "retry"},
            )
            return NotificationResult(
                delivered=[], invalid_tokens=[], transient_failures=list(tokens)
            )
        delivered: list[str] = []
        invalid: list[str] = []
        transient: list[str] = []
        for index, token in enumerate(tokens):
            if index >= len(responses):
                # Truncated batch: the provider never answered for this token.
                transient.append(token)
                continue
            result = responses[index]
            if getattr(result, "success", False):
                delivered.append(token)
            elif _is_invalid_token(getattr(result, "exception", None)):
                invalid.append(token)
            else:
                transient.append(token)
        return NotificationResult(
            delivered=delivered, invalid_tokens=invalid, transient_failures=transient
        )

    def notify(self, title: str, body: str) -> None:  # deprecated compat shim
        self.send(Notification(title=title, body=body, data={}), [])
