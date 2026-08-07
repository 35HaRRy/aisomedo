class DojoError(Exception):
    pass


class ActivePackageExists(DojoError):
    pass


class NoActivePackage(DojoError):
    pass
