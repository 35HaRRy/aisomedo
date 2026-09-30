"""Transport tests for the Firebase Admin SDK wiring.

Every message is a genuine ``firebase_admin.messaging`` type and the only
substituted piece is the network call, so message construction, response
mapping and application setup are verified against the SDK itself without
credentials, a project or a socket.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from dojo.adapters.fcm import (
    FCM_APP_NAME,
    FCM_HTTP_TIMEOUT_SECONDS,
    FCM_STATUS_CONFIG,
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


def test_sdk_error_codes_are_uppercase_and_shared_between_faults() -> None:
    """The SDK facts the classification relies on, pinned against the installed version.

    ``UnregisteredError`` inherits the shared ``NOT_FOUND`` code, so a
    code-driven check would also match a wrong project id; the class name is
    the only thing that distinguishes an unregistered token.
    """
    assert messaging.UnregisteredError("gone").code == exceptions.NOT_FOUND
    assert messaging.SenderIdMismatchError("other project").code == exceptions.PERMISSION_DENIED
    assert exceptions.InvalidArgumentError("bad").code == exceptions.INVALID_ARGUMENT
    assert issubclass(messaging.UnregisteredError, exceptions.NotFoundError)
    assert not issubclass(messaging.SenderIdMismatchError, messaging.UnregisteredError)


def test_unregistered_token_is_reported_invalid() -> None:
    noti, _sender = notifier(
        lambda message: all_failed(message, messaging.UnregisteredError("unregistered"))
    )

    result = noti.send(OPERATIONAL, ["token-a"])

    assert result.invalid_tokens == ["token-a"]
    assert result.transient_failures == []
    assert result.delivered == []


def test_a_shared_not_found_code_alone_never_deletes_a_registration() -> None:
    """A non-``UnregisteredError`` carrying the same code stays retryable."""
    noti, _sender = notifier(
        lambda message: all_failed(message, exceptions.NotFoundError("unknown project"))
    )

    result = noti.send(OPERATIONAL, ["token-a"])

    assert result.invalid_tokens == []
    assert result.transient_failures == ["token-a"]


def test_sender_id_mismatch_is_a_configuration_fault_not_a_dead_token() -> None:
    noti, _sender = notifier(
        lambda message: all_failed(message, messaging.SenderIdMismatchError("other project"))
    )

    result = noti.send(OPERATIONAL, ["token-a", "token-b"])

    assert result.invalid_tokens == []
    assert result.transient_failures == ["token-a", "token-b"]


def test_sender_id_mismatch_is_logged_as_a_configuration_fault(
    caplog: pytest.LogCaptureFixture,
) -> None:
    noti, _sender = notifier(
        lambda message: all_failed(message, messaging.SenderIdMismatchError("other project"))
    )

    with caplog.at_level(logging.WARNING, logger="dojo.adapters.fcm"):
        noti.send(OPERATIONAL, ["token-a", "token-b"])

    records = [
        record for record in caplog.records
        if getattr(record, "event", "") == "fcm.sender_id_mismatch"
    ]
    assert [record.status for record in records] == [FCM_STATUS_CONFIG]
    assert "2" in records[0].getMessage()
    # A mis-provisioned deployment must stay separable from an outage, and a
    # token never reaches a log line.
    assert "token-a" not in caplog.text


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
        FcmNotifier(messaging=FakeSender(), admin=admin, project_id="dojo-prod")

    assert admin.initialized == []


@pytest.mark.parametrize("project_id", [None, "", "   "])
def test_missing_project_id_fails_at_startup_not_on_the_first_send(
    project_id: str | None,
) -> None:
    """FCM is addressed by project, so an unknown one must stop startup.

    Without this the SDK falls back to whichever project the credential names,
    or raises a provider error on the first send — after an operator has
    already been told the deployment was fine. The credential is never read
    here, so ``admin.initialized`` staying empty also proves the check happens
    before any provider round trip.
    """
    admin = FakeAdmin()

    with pytest.raises(RuntimeError, match="no Firebase project id"):
        FcmNotifier(messaging=FakeSender(), admin=admin, project_id=project_id)

    assert admin.initialized == []


def test_a_reused_app_does_not_recheck_the_project_id() -> None:
    """The project check only costs a deployment that is initializing.

    Every notifier after the first reuses the named app, and a re-check would
    make a second notifier in the same process fail for a setting the first one
    already satisfied.
    """
    admin = FakeAdmin()
    first = FcmNotifier(messaging=FakeSender(), admin=admin, project_id="dojo-prod")

    second = FcmNotifier(messaging=FakeSender(), admin=admin)

    assert first._app is second._app
    assert len(admin.initialized) == 1


def test_the_project_id_failure_names_the_setting_not_the_provider() -> None:
    """The operator's fix is an environment variable, so the message says which.

    A generic "FCM is misconfigured" sends the reader to the credential file,
    which is not the missing setting, and a provider response would risk
    echoing request content into an exception an operator pastes into a ticket.
    """
    with pytest.raises(RuntimeError, match="FCM_PROJECT_ID"):
        FcmNotifier(messaging=FakeSender(), admin=FakeAdmin())
