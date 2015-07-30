class P2PException(Exception):
    pass


class P2PSlugTaken(P2PException):
    pass


class P2PNotFound(P2PException):
    pass


class P2PUniqueConstraintViolated(P2PException):
    pass