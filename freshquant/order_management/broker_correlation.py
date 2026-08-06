# -*- coding: utf-8 -*-

import re
from hashlib import sha256

from freshquant.order_management.broker_identity import (
    BrokerIdentityError,
    normalize_identifier,
)

_TOKEN_PREFIX = "FQOM"
_TOKEN_PATTERN = re.compile(r"^FQOM[0-9a-f]{20}$")


def build_broker_correlation_token(internal_order_id):
    normalized = normalize_identifier(internal_order_id)
    if normalized is None:
        raise BrokerIdentityError(
            "internal_order_id is required for broker correlation"
        )
    token = f"{_TOKEN_PREFIX}{sha256(normalized.encode('utf-8')).hexdigest()[:20]}"
    if len(token) != 24:  # pragma: no cover
        raise BrokerIdentityError("broker correlation token length is invalid")
    return token


def normalize_broker_correlation_token(value):
    normalized = normalize_identifier(value)
    if normalized is None or _TOKEN_PATTERN.fullmatch(normalized) is None:
        return None
    return normalized


def looks_like_broker_correlation_token(value):
    normalized = normalize_identifier(value)
    return bool(normalized and normalized.startswith(_TOKEN_PREFIX))
