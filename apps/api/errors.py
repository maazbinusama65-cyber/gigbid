"""Domain errors raised by services and mapped to JSON responses in main.py."""
from __future__ import annotations


class ApiError(Exception):
    status_code = 400
    error = "bad_request"

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail)
        self.detail = detail or self.error.replace("_", " ")


class NotFound(ApiError):
    status_code = 404
    error = "not_found"


class Conflict(ApiError):
    status_code = 409
    error = "conflict"


class Unauthorized(ApiError):
    status_code = 401
    error = "unauthorized"


class MarketplaceUnavailable(ApiError):
    status_code = 503
    error = "marketplace_unavailable"


class TooManyRequests(ApiError):
    status_code = 429
    error = "too_many_requests"
