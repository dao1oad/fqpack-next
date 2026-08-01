from __future__ import annotations

from typing import Any


class FqCopilotProductionEngine:
    def __init__(self, module=None) -> None:
        self._module = module

    def calculate(
        self, bars: list[dict[str, Any]], profile: dict[str, Any]
    ) -> list[list[int]]:
        return self.calculate_with_metadata(bars, profile)["sequences"]

    def calculate_with_metadata(
        self, bars: list[dict[str, Any]], profile: dict[str, Any]
    ) -> dict[str, Any]:
        module = self._load_module()
        args = self._native_args(bars, profile)
        batch = getattr(module, "fq_clxs_all", None)
        if not callable(batch):
            return self._single_model_fallback(
                module, args, reason="fq_clxs_all_unavailable"
            )
        try:
            rows = batch(*args, 1)
            calculation_mode = "batch_production_v1"
            fallback_reason = None
        except TypeError as exc:
            if not self._is_legacy_batch_signature_error(exc):
                raise
            return self._single_model_fallback(
                module, args, reason="fq_clxs_all_missing_switch_opt"
            )
        return {
            "sequences": [[int(value) for value in row] for row in rows],
            "calculation_mode": calculation_mode,
            "fallback_reason": fallback_reason,
        }

    def s0002_entrypoint3_evidence(
        self, bars: list[dict[str, Any]], profile: dict[str, Any]
    ) -> dict[str, list[Any]]:
        module = self._load_module()
        function = getattr(module, "fq_s0002_entrypoint3_evidence", None)
        if not callable(function):
            return {
                "trigger_codes": [0] * len(bars),
                "triggers": [None] * len(bars),
            }
        evidence = dict(function(*self._native_args(bars, profile), 1) or {})
        trigger_codes = list(evidence.get("trigger_codes") or [])
        triggers = list(evidence.get("triggers") or [])
        if len(trigger_codes) != len(bars) or len(triggers) != len(bars):
            raise RuntimeError("S0002 structural evidence must align with input bars")
        return {"trigger_codes": trigger_codes, "triggers": triggers}

    def health(self) -> dict[str, Any]:
        try:
            module = self._load_module()
        except Exception as exc:  # noqa: BLE001 - health reports import failures
            return {
                "status": "unavailable",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        batch_available = callable(getattr(module, "fq_clxs_all", None))
        single_available = callable(getattr(module, "fq_clxs", None))
        evidence_available = callable(
            getattr(module, "fq_s0002_entrypoint3_evidence", None)
        )
        calculation_available = batch_available or single_available
        missing_capabilities = []
        if not batch_available:
            missing_capabilities.append("fq_clxs_all")
        if not calculation_available:
            missing_capabilities.append("production_calculation")
        if not evidence_available:
            missing_capabilities.append("fq_s0002_entrypoint3_evidence")
        if not calculation_available:
            status = "unavailable"
        elif batch_available and evidence_available:
            status = "ready"
        else:
            status = "degraded"
        return {
            "status": status,
            "batch_available": batch_available,
            "single_available": single_available,
            "calculation_available": calculation_available,
            "s0002_evidence_available": evidence_available,
            "missing_capabilities": missing_capabilities,
        }

    def _load_module(self):
        if self._module is None:
            import fqcopilot

            self._module = fqcopilot
        return self._module

    def _native_args(self, bars, profile) -> tuple[Any, ...]:
        return (
            len(bars),
            [float(item["high"]) for item in bars],
            [float(item["low"]) for item in bars],
            [float(item["open"]) for item in bars],
            [float(item["close"]) for item in bars],
            [float(item["volume"]) for item in bars],
            int(profile["wave_opt"]),
            int(profile["stretch_opt"]),
            int(profile["trend_opt"]),
        )

    def _single_model_fallback(
        self, module, args: tuple[Any, ...], *, reason: str
    ) -> dict[str, Any]:
        single = getattr(module, "fq_clxs", None)
        if not callable(single):
            raise TypeError("fqcopilot production CLX entrypoints are unavailable")
        rows = [single(*args, 10000 + model_id) for model_id in range(18)]
        return {
            "sequences": [[int(value) for value in row] for row in rows],
            "calculation_mode": "single_model_fallback",
            "fallback_reason": reason,
        }

    def _is_legacy_batch_signature_error(self, exc: TypeError) -> bool:
        message = str(exc).lower()
        return any(
            fragment in message
            for fragment in (
                "positional argument",
                "takes exactly",
                "takes at most",
                "expected at most",
            )
        )
