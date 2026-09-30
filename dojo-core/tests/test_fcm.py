"""Transport tests for the Firebase Admin SDK wiring.

Every message is a genuine ``firebase_admin.messaging`` type and the only
substituted piece is the network call, so message construction, response
mapping and application setup are verified against the SDK itself without
credentials, a project or a socket.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from dojo.adapters.fcm import (
    FCM_APP_NAME,
    FCM_HTTP_TIMEOUT_SECONDS,
    MULTICAST_TOKEN_LIMIT,
    FcmNotifier,
)
from dojo.model import Notification
from firebase_admin import exceptions, messaging

OPERATIONAL = Notification(
    title="Disk alanı azalıyor",
    body="media hedefinde boş alan oranı düşük.",
    data={"type": "operational_alert", "alert_id": "alert-1", "kind": "disk.low"},
)
REVIEW = Notification(
    title="Yayın İncelemesi Bekliyor",
    body="Paketiniz incelemeyi bekliyor.",
    data={"type": "review_required", "review_id": "7"},
)


def delivered(message: messaging.MulticastMessage) -> messaging.BatchResponse:
    return messaging.BatchResponse(
        [
            messaging.SendResponse({"name": f"projects/p/messages/{index}"}, None)
            for index in range(len(message.tokens))
        ]
    )


def all_failed(message: messaging.MulticastMessage, error: Exception) -> messaging.BatchResponse:
    return messaging.BatchResponse(
        [messaging.SendResponse(None, error) for _ in message.tokens]
    )


class FakeSender:
    """The real messaging module with only the network call replaced."""

    def __init__(self, responder=None) -> None:
        self.responder = responder or delivered
        self.sent: list[tuple[messaging.MulticastMessage, object]] = []

    def __getattr__(self, name: str):  # message types stay the SDK's own
        return getattr(messaging, name)

    def send_each_for_multicast(self, message, dry_run=False, app=None):
        self.sent.append((message, app))
        return self.responder(message)


def notifier(responder=None, **kwargs) -> tuple[FcmNotifier, FakeSender]:
    sender = FakeSender(responder)
    return FcmNotifier(messaging=sender, app=object(), **kwargs), sender


# --- message construction ---------------------------------------------------


def test_domain_notification_becomes_an_sdk_message_with_a_stable_tag() -> None:
    noti, sender = notifier()

    result = noti.send(OPERATIONAL, ["token-a", "token-b"])

    assert result.delivered == ["token-a", "token-b"]
    message, _app = sender.sent[0]
    assert isinstance(message, messaging.MulticastMessage)
    assert isinstance(message.notification, messaging.Notification)
    assert message.notification.title == OPERATIONAL.title
    assert message.notification.body == OPERATIONAL.body
    # The tag is the durable alert identity, so a duplicate send replaces the
    # first notification in the Android tray instead of stacking.
    assert message.android.notification.tag == OPERATIONAL.data["alert_id"]
    assert message.tokens == ["token-a", "token-b"]


def test_notification_data_is_string_only() -> None:
    noti, sender = notifier()

    noti.send(Notification(title="t", body="b", data={"count": 3, "ok": "yes"}), ["token-a"])

    message, _app = sender.sent[0]
    assert message.data == {"count": "3", "ok": "yes"}
    assert all(isinstance(value, str) for value in message.data.values())


def test_message_without_an_alert_id_carries_no_android_tag() -> None:
    noti, sender = notifier()

    noti.send(REVIEW, ["token-a"])

    assert sender.sent[0][0].android is None


def test_batches_are_chunked_at_the_sdk_limit() -> None:
    noti, sender = notifier()
    tokens = [f"token-{index}" for index in range(MULTICAST_TOKEN_LIMIT + 1)]

    result = noti.send(OPERATIONAL, tokens)

    assert [len(message.tokens) for message, _ in sender.sent] == [MULTICAST_TOKEN_LIMIT, 1]
    assert result.delivered == tokens


def test_no_tokens_never_calls_the_provider() -> None:
    noti, sender = notifier()

    result = noti.send(OPERATIONAL, [])

    assert (result.delivered, result.invalid_tokens, result.transient_failures) == ([], [], [])
    assert sender.sent == []


# --- response mapping -------------------------------------------------------


def test_unregistered_token_is_reported_invalid() -> None:
    noti, _sender = notifier(
        lambda message: all_failed(message, messaging.UnregisteredError("unregistered"))
    )

    result = noti.send(OPERATIONAL, ["token-a"])

    assert result.invalid_tokens == ["token-a"]
    assert result.transient_failures == []
    assert result.delivered == []


def test_invalid_argument_stays_transient_because_it_can_be_a_bad_payload() -> None:
    noti, _sender = notifier(
        lambda message: all_failed(message, exceptions.InvalidArgumentError("invalid payload"))
    )

    result = noti.send(OPERATIONAL, ["token-a"])

    assert result.invalid_tokens == []
    assert result.transient_failures == ["token-a"]


def test_every_token_lands_in_exactly_one_category() -> None:
    outcomes = [None, messaging.UnregisteredError("gone"), exceptions.InvalidArgumentError("bad")]

    def responder(message: messaging.MulticastMessage) -> messaging.BatchResponse:
        return messaging.BatchResponse(
            [
                messaging.SendResponse({"name": "n"} if error is None else None, error)
                for error in outcomes
            ]
        )

    noti, _sender = notifier(responder)

    result = noti.send(OPERATIONAL, ["token-a", "token-b", "token-c"])

    assert result.delivered == ["token-a"]
    assert result.invalid_tokens == ["token-b"]
    assert result.transient_failures == ["token-c"]


def test_truncated_response_keeps_unmapped_tokens_retryable() -> None:
    def responder(message: messaging.MulticastMessage) -> messaging.BatchResponse:
        return messaging.BatchResponse([messaging.SendResponse({"name": "n"}, None)])

    noti, _sender = notifier(responder)

    result = noti.send(OPERATIONAL, ["token-a", "token-b"])

    assert result.delivered == ["token-a"]
    assert result.transient_failures == ["token-b"]


def test_unknown_response_shape_never_counts_as_delivered() -> None:
    noti, _sender = notifier(lambda message: object())

    result = noti.send(OPERATIONAL, ["token-a", "token-b"])

    assert result.delivered == []
    assert result.transient_failures == ["token-a", "token-b"]


def test_missing_send_method_raises_instead_of_claiming_success() -> None:
    class NoSend:
        """Message types only: the transport entry point is absent."""

        Notification = staticmethod(messaging.Notification)
        MulticastMessage = staticmethod(messaging.MulticastMessage)
        AndroidConfig = staticmethod(messaging.AndroidConfig)
        AndroidNotification = staticmethod(messaging.AndroidNotification)

    noti = FcmNotifier(messaging=NoSend(), app=object())

    with pytest.raises(RuntimeError, match="send_each_for_multicast"):
        noti.send(OPERATIONAL, ["token-a"])


# --- application setup ------------------------------------------------------


class FakeAdmin:
    """Minimal stand-in for the ``firebase_admin`` package surface."""

    def __init__(self, *, credential_error: Exception | None = None) -> None:
        self.credential_error = credential_error
        self.credentials = SimpleNamespace(ApplicationDefault=self._application_default)
        self.apps: dict[str, object] = {}
        self.initialized: list[object] = []

    def _application_default(self) -> str:
        if self.credential_error is not None:
            raise self.credential_error
        return "application-default-credential"

    def get_app(self, name: str | None) -> object:
        if name not in self.apps:
            raise ValueError(f"App {name} not initialized")
        return self.apps[name]

    def initialize_app(self, credential, options, name=None):
        if name in self.apps:
            raise ValueError(f"App {name} already exists")
        app = SimpleNamespace(name=name, options=options, credential=credential)
        self.apps[name] = app
        self.initialized.append(app)
        return app


def test_application_is_initialized_once_with_timeout_and_project_then_reused() -> None:
    admin = FakeAdmin()
    sender = FakeSender()
    first = FcmNotifier(messaging=sender, admin=admin, project_id="dojo-prod")
    second = FcmNotifier(messaging=sender, admin=admin)

    assert len(admin.initialized) == 1
    app = admin.apps[FCM_APP_NAME]
    assert first._app is second._app is app
    assert app.options == {"httpTimeout": FCM_HTTP_TIMEOUT_SECONDS, "projectId": "dojo-prod"}
    assert app.credential == "application-default-credential"

    first.send(OPERATIONAL, ["token-a"])

    assert sender.sent[0][1] is app


def test_unusable_credentials_fail_startup_instead_of_degrading() -> None:
    admin = FakeAdmin(
        credential_error=RuntimeError("GOOGLE_APPLICATION_CREDENTIALS is not set")
    )

    with pytest.raises(RuntimeError, match="FCM"):
        FcmNotifier(messaging=FakeSender(), admin=admin)

    assert admin.initialized == []
