class DojoError(Exception):
    pass


class ActivePackageExists(DojoError):
    pass


class NoActivePackage(DojoError):
    pass


class PairingError(DojoError):
    pass


class PairingCodeInvalid(PairingError):
    pass


class PairingCodeExpired(PairingError):
    pass


class PairingCodeConsumed(PairingError):
    pass


class ClientNotFound(PairingError):
    pass


class ConsentError(DojoError):
    pass


class ConsentPolicyDowngrade(ConsentError):
    pass


class NoConsentPolicy(ConsentError):
    pass


class UploadNotFound(DojoError):
    pass


class UploadNotReceiving(DojoError):
    pass


class UploadChecksumMismatch(DojoError):
    pass


class UploadTooLarge(DojoError):
    pass


class PackageLimitExceeded(DojoError):
    pass


class UploadIncomplete(DojoError):
    pass


class UploadConflict(DojoError):
    pass


class UploadInvalidFilename(DojoError):
    pass


class UploadDecisionInvalid(DojoError):
    pass


class JobNotFound(DojoError):
    pass


class MediaValidationError(DojoError):
    pass


class PackageCompleted(DojoError):
    pass


class MediaNotFound(DojoError):
    pass


class MediaNotRemovable(DojoError):
    pass


class MediaNotRestorable(DojoError):
    pass


class MontageOrderInvalid(DojoError):
    pass


class MontageTrimInvalid(DojoError):
    pass


class MontageDurationExceeded(DojoError):
    pass


class LogoNotConfigured(DojoError):
    pass


class RenderFailed(DojoError):
    pass


class PlanInvalid(DojoError):
    pass


class ManualPublishConflict(DojoError):
    pass


class SkipRequiresConfirmation(DojoError):
    pass


class RescheduleTimeInvalid(DojoError):
    pass


class ReviewStale(DojoError):
    pass


class ReviewAlreadyHandled(DojoError):
    def __init__(self, message: str, review: object | None = None) -> None:
        super().__init__(message)
        self.review = review


class ReviewNotFound(DojoError):
    pass


class ReminderPolicyInvalid(DojoError):
    pass


class PushTokenInvalid(DojoError):
    pass
