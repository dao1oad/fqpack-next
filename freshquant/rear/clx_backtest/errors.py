from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ApiError(Exception):
    code: str
    message: str
    status_code: int = 400
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        error: dict[str, object] = {
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            error["details"] = self.details
        return {"error": error}


def invalid_request(message: str, **details: object) -> ApiError:
    return ApiError("INVALID_REQUEST", message, 400, details)


def not_found(resource: str, identifier: str) -> ApiError:
    return ApiError(
        "NOT_FOUND",
        f"{resource} not found",
        404,
        {"resource": resource, "id": identifier},
    )


def conflict(code: str, message: str, **details: object) -> ApiError:
    return ApiError(code, message, 409, details)
