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
