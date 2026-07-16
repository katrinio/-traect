from __future__ import annotations


class TraectError(Exception):
    pass


class NotFoundError(TraectError):
    pass


class ValidationError(TraectError):
    pass

