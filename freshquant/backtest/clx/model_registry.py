"""Versioned semantic registry for the 18 CLX research models."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

MODEL_REGISTRY_VERSION = "clx-18-v1"
S0002_LEGACY_ENTRYPOINT3_SEMANTIC = "S0002_NORMAL_FRACTAL_LEGACY_3"

ENTRYPOINT_SEMANTICS: dict[int, str] = {
    1: "MODEL_STRUCTURAL",
    2: "PIN_BAR",
    3: "ENGULFING",
    4: "STRONG_FRACTAL",
    5: "MA5_TURN",
    6: "PRICE_VOLUME_CONFIRMATION",
    7: "MACD_CROSS",
}

_RELATIONS: dict[int, dict[str, str | None]] = {
    8: {
        "relation": "ROOT",
        "parent_model_code": None,
        "independence_root": "S0008",
    },
    13: {
        "relation": "SUBSET_OF",
        "parent_model_code": "S0008",
        "independence_root": "S0008",
    },
    14: {
        "relation": "SUBSET_OF",
        "parent_model_code": "S0008",
        "independence_root": "S0008",
    },
    16: {
        "relation": "ROOT",
        "parent_model_code": None,
        "independence_root": "S0016",
    },
    17: {
        "relation": "VARIANT_OF",
        "parent_model_code": "S0016",
        "independence_root": "S0016",
    },
}

_FAMILIES = {
    8: "source_proven_relationship_group",
    13: "source_proven_relationship_group",
    14: "source_proven_relationship_group",
    16: "support_resistance_reversal",
    17: "support_resistance_reversal",
}


def _model(model_id: int) -> dict[str, Any]:
    model_code = f"S{model_id:04d}"
    relation = _RELATIONS.get(
        model_id,
        {
            "relation": "ROOT",
            "parent_model_code": None,
            "independence_root": model_code,
        },
    )
    return {
        "registry_version": MODEL_REGISTRY_VERSION,
        "model_id": model_id,
        "model_code": model_code,
        "title": f"CLX {model_code}",
        "family": _FAMILIES.get(model_id, f"clx_model_{model_id:04d}"),
        **relation,
        "occurrence_semantics": (
            "MODEL_LOCAL_COUNTER_NOT_COMPARABLE_ACROSS_MODELS_WITHOUT_AN_"
            "EXPLICIT_NORMALIZATION_RULE"
        ),
        "implementation_sha": None,
        "implementation_sha_source": "engine_identity.native_module_sha256",
        "enabled": True,
    }


_REGISTRY: dict[str, Any] = {
    "registry_version": MODEL_REGISTRY_VERSION,
    "entrypoints": [
        {"entrypoint": entrypoint, "default_semantic": semantic}
        for entrypoint, semantic in ENTRYPOINT_SEMANTICS.items()
    ],
    "models": [_model(model_id) for model_id in range(18)],
    "semantic_overrides": [
        {
            "model_id": 2,
            "model_code": "S0002",
            "entrypoint": 3,
            "default_semantic": "ENGULFING",
            "legacy_semantic": S0002_LEGACY_ENTRYPOINT3_SEMANTIC,
            "overload": True,
            "source_control_flow": (
                "S0002 first evaluates shared entrypoint predicates; when none "
                "matches, NORMAL_FRACTAL plus the support/resistance condition is "
                "encoded with legacy entrypoint 3"
            ),
            "row_resolution": (
                "The detailed native base-predicate mask remains unmodified by "
                "model primary codes. Base bit 3 resolves to ENGULFING; an absent "
                "base bit 3 resolves the encoded S0002 branch to "
                "S0002_NORMAL_FRACTAL_LEGACY_3"
            ),
            "mask_provenance": (
                "For the legacy fallback, entrypoint-3 is absent from the native "
                "base-predicate mask and is recorded in the synthetic-primary "
                "mask used to satisfy the completed primary-bit invariant"
            ),
            "ranking_dimension": "primary_trigger_semantic",
            "ranking_rule": (
                "S0002_NORMAL_FRACTAL_LEGACY_3 and ENGULFING remain separate "
                "trigger semantics"
            ),
            "source_refs": [
                "morningglory/fqcopilot/cpp/copilot/S0002.cpp",
                "morningglory/fqcopilot/cpp/copilot/batch_calculator.cpp",
                "morningglory/fqcopilot/cpp/copilot/signal_utils.h",
                "morningglory/fqcopilot/cpp/indicator/engulfing.cpp",
            ],
        }
    ],
}


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def get_model_registry() -> dict[str, Any]:
    """Return an isolated copy so callers cannot mutate the global contract."""

    return copy.deepcopy(_REGISTRY)


def model_registry_sha256() -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(_REGISTRY)).hexdigest()


def primary_trigger_semantic(model_id: int, entrypoint: int) -> str:
    """Return the default semantic; S0002/3 needs prefix-level resolution."""

    if model_id == 2 and entrypoint == 3:
        return "S0002_ENTRYPOINT3_REQUIRES_PREFIX_RESOLUTION"
    try:
        return ENTRYPOINT_SEMANTICS[entrypoint]
    except KeyError as exc:
        raise ValueError(f"entrypoint must be in 1..7, got {entrypoint}") from exc
