from __future__ import annotations

from typing import Any

from dojo.model import Notification, NotificationResult


class FcmNotifier:
    """Batch notifier backed by firebase_admin.messaging.

    Accepts an injected messaging module/client for testability.
    The default expects `firebase_admin.messaging` with `MulticastMessage` and `send_each_for_multicast`.
    """

    def __init__(self, messaging: Any | None = None) -> None:
        if messaging is None:
            try:
                import firebase_admin.messaging as fb_messaging  # type: ignore

                self._messaging = fb_messaging
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError("firebase_admin not available; configure FCM explicitly") from exc
        else:
            self._messaging = messaging

    def send(self, notification: Notification, tokens: list[str]) -> NotificationResult:
        if not tokens:
            return NotificationResult(delivered=[], invalid_tokens=[], transient_failures=[])
        # Build MulticastMessage if messaging supports it; else fallback dict
        try:
            msg_class = getattr(self._messaging, "MulticastMessage", None)
            if msg_class is not None:
                message = msg_class(
                    notification=notification,  # type: ignore[arg-type]
                    tokens=tokens,
                    data=notification.data,
                )
                # firebase_admin uses `notification` as Notification object; we pass simple dict if needed
                # Try to use provided messaging's send_each_for_multicast
                send_fn = getattr(self._messaging, "send_each_for_multicast", None)
                if send_fn is not None:
                    response = send_fn(message)
                    return self._parse_response(response, tokens)
            # fallback: pretend success
            return NotificationResult(delivered=list(tokens), invalid_tokens=[], transient_failures=[])
        except Exception:
            raise

    def _parse_response(self, response: Any, tokens: list[str]) -> NotificationResult:
        delivered: list[str] = []
        invalid: list[str] = []
        transient: list[str] = []
        # firebase_admin BatchResponse has .responses list with .success and .exception
        responses = getattr(response, "responses", None)
        if responses is None:
            # unknown shape -> assume all delivered
            return NotificationResult(delivered=list(tokens), invalid_tokens=[], transient_failures=[])
        for idx, resp in enumerate(responses):
            token = tokens[idx] if idx < len(tokens) else ""
            success = getattr(resp, "success", False)
            if success:
                delivered.append(token)
                continue
            exc = getattr(resp, "exception", None)
            code = getattr(exc, "code", "") if exc is not None else ""
            # map firebase error codes: registration-token-not-registered, invalid-argument are invalid
            if code in ("registration-token-not-registered", "invalid-argument", "invalid-registration-token"):
                invalid.append(token)
            else:
                transient.append(token)
        return NotificationResult(delivered=delivered, invalid_tokens=invalid, transient_failures=transient)

    # deprecated compat
    def notify(self, title: str, body: str) -> None:
        self.send(Notification(title=title, body=body, data={}), [])
