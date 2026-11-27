"""Typed service errors. The API layer maps them to a uniform JSON error envelope."""
from __future__ import annotations


class ServiceError(Exception):
    status = 500
    code = "internal_error"

    def __init__(self, message: str, *, code: str | None = None, headers: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.headers = headers or {}


class BadRequest(ServiceError):
    status, code = 400, "bad_request"


class Unauthorized(ServiceError):
    status, code = 401, "unauthorized"


class Forbidden(ServiceError):
    status, code = 403, "forbidden"


class NotFound(ServiceError):
    status, code = 404, "not_found"


class Conflict(ServiceError):
    status, code = 409, "conflict"


class PayloadTooLarge(ServiceError):
    status, code = 413, "payload_too_large"


class RateLimited(ServiceError):
    status, code = 429, "rate_limited"

    def __init__(self, retry_after: float):
        secs = max(1, int(retry_after + 0.999))
        super().__init__(f"Too many requests. Try again in {secs}s.", headers={"Retry-After": str(secs)})
        self.retry_after = secs


class Unavailable(ServiceError):
    status, code = 503, "unavailable"
