import json

from freshquant.position_management.dashboard_service import (
    DEFAULT_SINGLE_SYMBOL_POSITION_LIMIT,
    _coerce_float,
    _normalize_symbol_position_limit_overrides,
)
from freshquant.position_management.repository import PositionManagementRepository


def normalize_symbol_position_limit_overrides(repository=None):
    repository = repository or PositionManagementRepository()
    raw_config = repository.get_config() or {}
    document = dict(raw_config)
    document.pop("_id", None)
    document["code"] = str(document.get("code") or "default").strip() or "default"
    document["enabled"] = True

    thresholds = (
        (document.get("thresholds") or {}) if isinstance(document, dict) else {}
    )
    default_limit = _coerce_float(
        thresholds.get("single_symbol_position_limit"),
        DEFAULT_SINGLE_SYMBOL_POSITION_LIMIT,
    )
    raw_overrides = (
        ((document.get("symbol_position_limits") or {}).get("overrides", {}) or {})
        if isinstance(document, dict)
        else {}
    )
    normalized_overrides = _normalize_symbol_position_limit_overrides(raw_overrides)
    effective_overrides = _normalize_symbol_position_limit_overrides(
        raw_overrides,
        default_limit=default_limit,
    )
    document["symbol_position_limits"] = {
        "overrides": effective_overrides,
    }
    repository.upsert_config(document)
    result = {
        "config_code": document["code"],
        "default_limit": default_limit,
        "raw_override_count": len(raw_overrides),
        "normalized_override_count": len(normalized_overrides),
        "effective_override_count": len(effective_overrides),
        "removed_override_count": len(normalized_overrides) - len(effective_overrides),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    normalize_symbol_position_limit_overrides()
