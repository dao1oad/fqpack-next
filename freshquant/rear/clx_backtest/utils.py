from __future__ import annotations

import base64
import binascii
import copy
import json
import re
import secrets
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

from .artifacts import canonical_json_bytes, content_hash
from .errors import ApiError, invalid_request

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
MAX_PAGE_SIZE = 200
MAX_JSON_BYTES = 256 * 1024


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def new_ulid() -> str:
    value = (int(time.time() * 1000) << 80) | int.from_bytes(
        secrets.token_bytes(10), "big"
    )
    chars: list[str] = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def canonical_json(value: object) -> bytes:
    return canonical_json_bytes(value)


def validate_plain_json(value: object, *, path: str = "$", depth: int = 0) -> None:
    if depth > 24:
        raise invalid_request("JSON nesting is too deep", path=path)
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise invalid_request("JSON number must be finite", path=path)
        return
    if isinstance(value, list):
        if len(value) > 10_000:
            raise invalid_request("JSON array is too large", path=path)
        for index, item in enumerate(value):
            validate_plain_json(item, path=f"{path}[{index}]", depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 2_000:
            raise invalid_request("JSON object is too large", path=path)
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise invalid_request("JSON keys must be non-empty strings", path=path)
            if key.startswith("$") or "." in key:
                raise invalid_request(
                    "Mongo operator-style keys are not accepted", path=path
                )
            validate_plain_json(item, path=f"{path}.{key}", depth=depth + 1)
        return
    raise invalid_request("Unsupported JSON value", path=path)


def validated_document(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise invalid_request(f"{field} must be a JSON object", field=field)
    validate_plain_json(value, path=field)
    try:
        encoded = canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise invalid_request(f"{field} is not canonical JSON", field=field) from exc
    if len(encoded) > MAX_JSON_BYTES:
        raise invalid_request(f"{field} is too large", field=field)
    return copy.deepcopy(value)


def validated_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise invalid_request(f"{field} has an invalid format", field=field)
    return value


def parse_page_size(raw: str | None) -> int:
    if raw is None:
        return 50
    try:
        value = int(raw)
    except ValueError as exc:
        raise invalid_request("page_size must be an integer") from exc
    if not 1 <= value <= MAX_PAGE_SIZE:
        raise invalid_request(
            f"page_size must be between 1 and {MAX_PAGE_SIZE}",
            minimum=1,
            maximum=MAX_PAGE_SIZE,
        )
    return value


def reject_unknown_keys(
    values: Mapping[str, object], allowed: Iterable[str], *, location: str
) -> None:
    unknown = sorted(set(values) - set(allowed))
    if unknown:
        raise invalid_request(
            f"Unsupported {location} field", location=location, fields=unknown
        )


def encode_cursor(kind: str, values: list[object]) -> str:
    payload = canonical_json({"v": 1, "kind": kind, "values": values})
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(raw: str | None, *, kind: str, length: int) -> list[object] | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw or len(raw) > 2048:
        raise ApiError("INVALID_CURSOR", "cursor is invalid", 400)
    try:
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (
        binascii.Error,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ApiError("INVALID_CURSOR", "cursor is invalid", 400) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("v") != 1
        or payload.get("kind") != kind
        or not isinstance(payload.get("values"), list)
        or len(payload["values"]) != length
    ):
        raise ApiError("INVALID_CURSOR", "cursor is invalid", 400)
    values = payload["values"]
    validate_plain_json(values, path="cursor")
    return values


def json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if value.__class__.__name__ == "ObjectId":
        return str(value)
    return value
