"""Versioned, canonical and strictly backward-looking CLX combination DSL.

The DSL is data, never executable Python/SQL.  Canonicalization is intentionally
strict because its UTF-8 JSON bytes are the content-addressed combination
identity consumed by ranking, portfolio and UI layers.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Iterable, Mapping

import polars as pl

from .model_registry import canonical_json_bytes, get_model_registry

DSL_VERSION = "1.0"
ALLOWED_LOOKBACKS = (1, 3, 5)
MASK_SOURCES = {
    "direction_base": "direction_base_trigger_mask",
    "synthetic_primary": "synthetic_primary_mask",
    "concurrent": "concurrent_trigger_mask",
}


class DslValidationError(ValueError):
    """Raised when an AST is outside the frozen JSON grammar."""


class DslEvaluationError(RuntimeError):
    """Raised when causal event inputs do not satisfy the evaluator contract."""


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _assert_keys(value: Mapping[str, Any], allowed: set[str], *, op: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise DslValidationError(f"{op} contains unsupported keys: {extra}")


def _integer(value: Any, *, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DslValidationError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise DslValidationError(f"{name} must be in {minimum}..{maximum}")
    return value


def _numeric_literal(value: Any, *, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DslValidationError(f"{name} must be numeric")
    if isinstance(value, float) and not math.isfinite(value):
        raise DslValidationError(f"{name} must be finite")
    return value


def _int_selector(
    value: Any,
    *,
    name: str,
    minimum: int,
    maximum: int,
    allowed_values: set[int] | None = None,
) -> dict[str, Any]:
    if value is None or value == "*":
        return {"any": True}
    if isinstance(value, int) and not isinstance(value, bool):
        value = {"in": [value]}
    elif isinstance(value, (list, tuple)):
        value = {"in": list(value)}
    if not isinstance(value, Mapping):
        raise DslValidationError(f"{name} must be an integer selector")
    if value == {"any": True}:
        return {"any": True}
    _assert_keys(value, {"in"}, op=name)
    raw_values = value.get("in")
    if not isinstance(raw_values, (list, tuple)) or not raw_values:
        raise DslValidationError(f"{name}.in must be a non-empty array")
    result = sorted(
        {
            _integer(item, name=name, minimum=minimum, maximum=maximum)
            for item in raw_values
        }
    )
    if allowed_values is not None and not set(result).issubset(allowed_values):
        raise DslValidationError(f"{name} contains unsupported values")
    return {"in": result}


def _string_selector(
    value: Any,
    *,
    name: str,
    allowed_values: set[str] | None = None,
) -> dict[str, Any]:
    if value is None or value == "*":
        return {"any": True}
    if isinstance(value, str):
        value = {"in": [value]}
    elif isinstance(value, (list, tuple)):
        value = {"in": list(value)}
    if not isinstance(value, Mapping):
        raise DslValidationError(f"{name} must be a string selector")
    if value == {"any": True}:
        return {"any": True}
    _assert_keys(value, {"in"}, op=name)
    raw_values = value.get("in")
    if not isinstance(raw_values, (list, tuple)) or not raw_values:
        raise DslValidationError(f"{name}.in must be a non-empty array")
    if any(not isinstance(item, str) or not item for item in raw_values):
        raise DslValidationError(f"{name}.in must contain non-empty strings")
    result = sorted(set(raw_values))
    if allowed_values is not None and not set(result).issubset(allowed_values):
        raise DslValidationError(f"{name} contains unsupported values")
    return {"in": result}


class ModelRelations:
    """Validated model dependency graph used by every voting operation."""

    def __init__(self, registry: Mapping[str, Any] | None = None) -> None:
        source = get_model_registry() if registry is None else dict(registry)
        models = source.get("models")
        if not isinstance(models, list) or not models:
            raise DslValidationError("model registry has no models")
        self.registry_version = str(source.get("registry_version"))
        self._by_code: dict[str, dict[str, Any]] = {}
        self._by_id: dict[int, dict[str, Any]] = {}
        for raw in models:
            if not isinstance(raw, Mapping):
                raise DslValidationError("model registry row must be an object")
            row = dict(raw)
            code = row.get("model_code")
            model_id = row.get("model_id")
            if not isinstance(code, str) or not isinstance(model_id, int):
                raise DslValidationError("model registry row misses code/id")
            if code in self._by_code or model_id in self._by_id:
                raise DslValidationError("model registry contains duplicate code/id")
            if row.get("relation") not in {"ROOT", "SUBSET_OF", "VARIANT_OF"}:
                raise DslValidationError(f"unsupported model relation for {code}")
            root = row.get("independence_root")
            if not isinstance(root, str) or not root:
                raise DslValidationError(f"model {code} has no independence_root")
            self._by_code[code] = row
            self._by_id[model_id] = row
        for code, row in self._by_code.items():
            relation = row["relation"]
            parent = row.get("parent_model_code")
            if relation == "ROOT":
                if parent is not None or row["independence_root"] != code:
                    raise DslValidationError(f"ROOT model {code} is inconsistent")
                continue
            if parent not in self._by_code:
                raise DslValidationError(f"model {code} has an unknown parent")
            if self._by_code[parent]["independence_root"] != row["independence_root"]:
                raise DslValidationError(
                    f"model {code} does not share its parent's independence root"
                )
        for code in self._by_code:
            seen: set[str] = set()
            cursor: str | None = code
            while cursor is not None:
                if cursor in seen:
                    raise DslValidationError(
                        "model registry contains a dependency cycle"
                    )
                seen.add(cursor)
                cursor = self._by_code[cursor].get("parent_model_code")

    @property
    def model_codes(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_code))

    def row(self, model_code: str) -> dict[str, Any]:
        try:
            return dict(self._by_code[model_code])
        except KeyError as exc:
            raise DslValidationError(f"unknown CLX model: {model_code}") from exc

    def root(self, model_code: str) -> str:
        return str(self.row(model_code)["independence_root"])

    def root_for_id(self, model_id: int) -> str:
        try:
            return str(self._by_id[model_id]["independence_root"])
        except KeyError as exc:
            raise DslEvaluationError(f"event has unknown model_id {model_id}") from exc

    def distinct_roots(self, model_codes: Iterable[str]) -> tuple[str, ...]:
        return tuple(sorted({self.root(code) for code in model_codes}))


def _canonical_signal(
    node: Mapping[str, Any], relations: ModelRelations
) -> dict[str, Any]:
    _assert_keys(
        node,
        {
            "op",
            "model",
            "direction",
            "occurrence",
            "primary_entrypoint",
            "primary_trigger_semantic",
        },
        op="signal",
    )
    model = _string_selector(
        node.get("model"),
        name="signal.model",
        allowed_values=set(relations.model_codes),
    )
    occurrence = _int_selector(
        node.get("occurrence"),
        name="signal.occurrence",
        minimum=1,
        maximum=99,
    )
    if occurrence != {"any": True} and model == {"any": True}:
        raise DslValidationError(
            "occurrence is model-local and requires an explicit model selector"
        )
    return {
        "op": "signal",
        "model": model,
        "direction": _int_selector(
            node.get("direction"),
            name="signal.direction",
            minimum=-1,
            maximum=1,
            allowed_values={-1, 1},
        ),
        "occurrence": occurrence,
        "primary_entrypoint": _int_selector(
            node.get("primary_entrypoint"),
            name="signal.primary_entrypoint",
            minimum=1,
            maximum=7,
        ),
        "primary_trigger_semantic": _string_selector(
            node.get("primary_trigger_semantic"),
            name="signal.primary_trigger_semantic",
        ),
    }


def _canonical_trigger_mask(
    node: Mapping[str, Any], relations: ModelRelations
) -> dict[str, Any]:
    _assert_keys(
        node,
        {
            "op",
            "source",
            "mode",
            "ids",
            "model",
            "direction",
            "occurrence",
            "primary_entrypoint",
            "primary_trigger_semantic",
            "event_filter",
        },
        op="trigger_mask",
    )
    source = node.get("source", "concurrent")
    mode = node.get("mode", "any")
    if source not in MASK_SOURCES:
        raise DslValidationError(f"unsupported trigger mask source: {source}")
    if mode not in {"any", "all", "none"}:
        raise DslValidationError(f"unsupported trigger mask mode: {mode}")
    ids = _int_selector(node.get("ids"), name="trigger_mask.ids", minimum=1, maximum=7)
    if ids == {"any": True}:
        raise DslValidationError("trigger_mask.ids is required")
    if "event_filter" in node:
        if any(
            key in node
            for key in (
                "model",
                "direction",
                "occurrence",
                "primary_entrypoint",
                "primary_trigger_semantic",
            )
        ):
            raise DslValidationError(
                "trigger_mask cannot mix canonical event_filter and raw filters"
            )
        raw_filter = node["event_filter"]
        if not isinstance(raw_filter, Mapping):
            raise DslValidationError("trigger_mask.event_filter must be an object")
        signal_filter = _canonical_signal({"op": "signal", **raw_filter}, relations)
    else:
        signal_filter = _canonical_signal(
            {
                "op": "signal",
                "model": node.get("model"),
                "direction": node.get("direction"),
                "occurrence": node.get("occurrence"),
                "primary_entrypoint": node.get("primary_entrypoint"),
                "primary_trigger_semantic": node.get("primary_trigger_semantic"),
            },
            relations,
        )
    return {
        "op": "trigger_mask",
        "source": source,
        "mode": mode,
        "ids": ids["in"],
        "event_filter": {
            key: value for key, value in signal_filter.items() if key != "op"
        },
    }


def _canonical_node(
    node: Any,
    relations: ModelRelations,
    factor_registry: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(node, Mapping):
        raise DslValidationError("DSL node must be an object")
    op = node.get("op")
    if op == "signal":
        return _canonical_signal(node, relations)
    if op == "trigger_mask":
        return _canonical_trigger_mask(node, relations)
    if op in {"and", "or"}:
        _assert_keys(node, {"op", "args"}, op=str(op))
        args = node.get("args")
        if not isinstance(args, (list, tuple)) or not args:
            raise DslValidationError(f"{op}.args must be a non-empty array")
        canonical: list[dict[str, Any]] = []
        for raw in args:
            child = _canonical_node(raw, relations, factor_registry)
            if child.get("op") == op:
                canonical.extend(child["args"])
            else:
                canonical.append(child)
        unique = {_digest(child): child for child in canonical}
        ordered = [unique[key] for key in sorted(unique)]
        if len(ordered) == 1:
            return ordered[0]
        return {"op": op, "args": ordered}
    if op == "not":
        _assert_keys(node, {"op", "expr"}, op="not")
        return {
            "op": "not",
            "expr": _canonical_node(node.get("expr"), relations, factor_registry),
        }
    if op == "same_day":
        _assert_keys(node, {"op", "expr"}, op="same_day")
        return {
            "op": "same_day",
            "expr": _canonical_node(node.get("expr"), relations, factor_registry),
        }
    if op in {"within", "not_exists"}:
        _assert_keys(node, {"op", "expr", "sessions", "include_current"}, op=str(op))
        sessions = _integer(
            node.get("sessions"), name=f"{op}.sessions", minimum=1, maximum=5
        )
        if sessions not in ALLOWED_LOOKBACKS:
            raise DslValidationError(
                f"{op}.sessions must be one of {ALLOWED_LOOKBACKS}"
            )
        include_current = node.get("include_current", True)
        if not isinstance(include_current, bool):
            raise DslValidationError(f"{op}.include_current must be boolean")
        return {
            "op": op,
            "expr": _canonical_node(node.get("expr"), relations, factor_registry),
            "sessions": sessions,
            "include_current": include_current,
        }
    if op == "sequence":
        _assert_keys(
            node,
            {"op", "args", "max_gap_sessions", "allow_same_session", "anchor_last"},
            op="sequence",
        )
        args = node.get("args")
        if not isinstance(args, (list, tuple)) or not 2 <= len(args) <= 3:
            raise DslValidationError("sequence.args must contain two or three nodes")
        gap = _integer(
            node.get("max_gap_sessions"),
            name="sequence.max_gap_sessions",
            minimum=1,
            maximum=5,
        )
        if gap not in ALLOWED_LOOKBACKS:
            raise DslValidationError(
                f"sequence.max_gap_sessions must be one of {ALLOWED_LOOKBACKS}"
            )
        allow_same = node.get("allow_same_session", False)
        anchor_last = node.get("anchor_last", True)
        if not isinstance(allow_same, bool) or not isinstance(anchor_last, bool):
            raise DslValidationError("sequence boolean defaults must be booleans")
        return {
            "op": "sequence",
            "args": [
                _canonical_node(item, relations, factor_registry) for item in args
            ],
            "max_gap_sessions": gap,
            "allow_same_session": allow_same,
            "anchor_last": anchor_last,
        }
    if op == "count":
        _assert_keys(
            node,
            {"op", "expr", "min", "max", "distinct", "sessions", "include_current"},
            op="count",
        )
        minimum = _integer(node.get("min", 1), name="count.min", minimum=1, maximum=18)
        maximum = _integer(node.get("max", 18), name="count.max", minimum=1, maximum=18)
        if minimum > maximum:
            raise DslValidationError("count.min exceeds count.max")
        if node.get("distinct", "independence_root") != "independence_root":
            raise DslValidationError("count only supports distinct_independence_root")
        sessions = _integer(
            node.get("sessions", 0), name="count.sessions", minimum=0, maximum=5
        )
        if sessions not in (0, *ALLOWED_LOOKBACKS):
            raise DslValidationError("count.sessions is outside the lookback whitelist")
        include_current = node.get("include_current", True)
        if not isinstance(include_current, bool):
            raise DslValidationError("count.include_current must be boolean")
        expr = _canonical_node(node.get("expr"), relations, factor_registry)
        if _contains_temporal(expr):
            raise DslValidationError("count.expr must be an event-local predicate")
        return {
            "op": "count",
            "expr": expr,
            "min": minimum,
            "max": maximum,
            "distinct": "independence_root",
            "sessions": sessions,
            "include_current": include_current,
        }
    if op == "factor":
        _assert_keys(node, {"op", "name", "comparison", "value"}, op="factor")
        name = node.get("name")
        if not isinstance(name, str) or name not in factor_registry:
            raise DslValidationError(
                f"factor is not registered with as-of lineage: {name}"
            )
        registration = factor_registry[name]
        if not registration.get("as_of") or not registration.get("lineage"):
            raise DslValidationError(f"factor registration is not causal: {name}")
        comparison = node.get("comparison")
        if comparison not in {"lt", "lte", "gt", "gte", "eq"}:
            raise DslValidationError(f"unsupported factor comparison: {comparison}")
        return {
            "op": "factor",
            "name": name,
            "comparison": comparison,
            "value": _numeric_literal(node.get("value"), name="factor.value"),
            "lineage_id": str(registration["lineage"]),
        }
    raise DslValidationError(f"unsupported DSL op: {op}")


def _contains_temporal(node: Mapping[str, Any]) -> bool:
    op = node["op"]
    if op in {"same_day", "within", "not_exists", "sequence", "count"}:
        return True
    if op in {"and", "or"}:
        return any(_contains_temporal(child) for child in node["args"])
    if op == "not":
        return _contains_temporal(node["expr"])
    return False


def canonicalize_combo(
    value: Mapping[str, Any],
    *,
    relations: ModelRelations | None = None,
    factor_registry: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate and canonicalize a complete combination definition."""

    if not isinstance(value, Mapping):
        raise DslValidationError("combination definition must be an object")
    _assert_keys(
        value,
        {"dsl_version", "action", "anchor", "target_direction", "where"},
        op="combination",
    )
    if value.get("dsl_version", DSL_VERSION) != DSL_VERSION:
        raise DslValidationError(f"unsupported dsl_version: {value.get('dsl_version')}")
    action = value.get("action", "PREDICT_DIRECTION")
    if action not in {"PREDICT_DIRECTION", "BUY_CANDIDATE", "EXIT_OR_VETO"}:
        raise DslValidationError(f"unsupported combination action: {action}")
    default_direction = (
        1 if action == "BUY_CANDIDATE" else -1 if action == "EXIT_OR_VETO" else None
    )
    target = value.get("target_direction", default_direction)
    if target not in {-1, 1}:
        raise DslValidationError(
            "target_direction must be explicit for PREDICT_DIRECTION"
        )
    if value.get("anchor", "reveal_date") != "reveal_date":
        raise DslValidationError("all combination clocks must anchor on reveal_date")
    effective_relations = relations or ModelRelations()
    factors = factor_registry or {}
    return {
        "dsl_version": DSL_VERSION,
        "action": action,
        "anchor": "reveal_date",
        "target_direction": target,
        "where": _canonical_node(value.get("where"), effective_relations, factors),
    }


def combo_id(canonical: Mapping[str, Any]) -> str:
    return "sha256:" + _digest(canonical)


def _node_complexity(node: Mapping[str, Any]) -> int:
    op = node["op"]
    if op in {"signal", "trigger_mask", "factor"}:
        return 1
    if op in {"and", "or", "sequence"}:
        return 1 + sum(_node_complexity(child) for child in node["args"])
    return 1 + _node_complexity(node["expr"])


def _selected_models(node: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    if node["op"] == "signal":
        result.update(node["model"].get("in", []))
    elif node["op"] == "trigger_mask":
        result.update(node["event_filter"]["model"].get("in", []))
    elif node["op"] in {"and", "or", "sequence"}:
        for child in node["args"]:
            result.update(_selected_models(child))
    elif node["op"] in {"not", "same_day", "within", "not_exists", "count"}:
        result.update(_selected_models(node["expr"]))
    return result


@dataclass(frozen=True, slots=True)
class ComboDefinition:
    combo_id: str
    canonical: dict[str, Any]
    canonical_json: str
    complexity: int
    model_roots: tuple[str, ...]

    @classmethod
    def from_value(
        cls,
        value: Mapping[str, Any],
        *,
        relations: ModelRelations | None = None,
        factor_registry: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> "ComboDefinition":
        effective_relations = relations or ModelRelations()
        canonical = canonicalize_combo(
            value, relations=effective_relations, factor_registry=factor_registry
        )
        encoded = canonical_json_bytes(canonical).decode("utf-8")
        return cls(
            combo_id=combo_id(canonical),
            canonical=canonical,
            canonical_json=encoded,
            complexity=_node_complexity(canonical["where"]),
            model_roots=effective_relations.distinct_roots(
                _selected_models(canonical["where"])
            ),
        )


_REQUIRED_EVENT_COLUMNS = {
    "signal_fact_id",
    "code",
    "reveal_date",
    "expected_model_id",
    "model_code",
    "direction",
    "occurrence",
    "primary_entrypoint",
    "primary_trigger_semantic",
    "direction_base_trigger_mask",
    "synthetic_primary_mask",
    "concurrent_trigger_mask",
}


def _selector_matches(selector: Mapping[str, Any], value: Any) -> bool:
    return bool(selector.get("any")) or value in selector.get("in", [])


FactorProvider = Callable[[str, int, str], float | int | None]


class EventIndex:
    """Read-only per-code/session index; every temporal operator scans backward."""

    def __init__(
        self,
        events: pl.DataFrame,
        calendar: pl.DataFrame,
        *,
        relations: ModelRelations | None = None,
        factor_provider: FactorProvider | None = None,
    ) -> None:
        missing = _REQUIRED_EVENT_COLUMNS - set(events.columns)
        if missing:
            raise DslEvaluationError(f"event outcomes miss columns: {sorted(missing)}")
        if not {"trade_date", "session_no"}.issubset(calendar.columns):
            raise DslEvaluationError("calendar misses trade_date/session_no")
        ordered = calendar.sort("session_no")
        sessions = ordered["session_no"].to_list()
        if sessions != list(range(1, ordered.height + 1)):
            raise DslEvaluationError("calendar session_no must be one-based contiguous")
        self._date_to_session = dict(
            zip(ordered["trade_date"].to_list(), sessions, strict=True)
        )
        self._relations = relations or ModelRelations()
        self._factor_provider = factor_provider
        self._events: dict[tuple[str, int], tuple[dict[str, Any], ...]] = {}
        grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for row in events.iter_rows(named=True):
            session = self._date_to_session.get(row["reveal_date"])
            if session is None:
                raise DslEvaluationError("event reveal_date is absent from calendar")
            grouped.setdefault((str(row["code"]), session), []).append(dict(row))
        for key, rows in grouped.items():
            self._events[key] = tuple(
                sorted(rows, key=lambda row: str(row["signal_fact_id"]))
            )

    def session_for_date(self, day: date) -> int:
        try:
            return self._date_to_session[day]
        except KeyError as exc:
            raise DslEvaluationError("anchor date is absent from calendar") from exc

    def events(self, code: str, start: int, end: int) -> tuple[dict[str, Any], ...]:
        if end < start:
            return ()
        return tuple(
            row
            for session in range(max(1, start), end + 1)
            for row in self._events.get((code, session), ())
        )

    def _event_matches(self, node: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
        op = node["op"]
        if op == "signal":
            return (
                _selector_matches(node["model"], row["model_code"])
                and _selector_matches(node["direction"], int(row["direction"]))
                and _selector_matches(node["occurrence"], int(row["occurrence"]))
                and _selector_matches(
                    node["primary_entrypoint"], int(row["primary_entrypoint"])
                )
                and _selector_matches(
                    node["primary_trigger_semantic"],
                    row["primary_trigger_semantic"],
                )
            )
        if op == "trigger_mask":
            event_filter = {"op": "signal", **node["event_filter"]}
            if not self._event_matches(event_filter, row):
                return False
            mask = int(row[MASK_SOURCES[node["source"]]])
            selected = sum(1 << (entrypoint - 1) for entrypoint in node["ids"])
            if node["mode"] == "all":
                return mask & selected == selected
            if node["mode"] == "any":
                return bool(mask & selected)
            return not bool(mask & selected)
        if op == "and":
            return all(self._event_matches(child, row) for child in node["args"])
        if op == "or":
            return any(self._event_matches(child, row) for child in node["args"])
        if op == "not":
            return not self._event_matches(node["expr"], row)
        raise DslEvaluationError(f"{op} is not an event-local predicate")

    def _matching_rows(
        self, node: Mapping[str, Any], code: str, start: int, end: int
    ) -> tuple[dict[str, Any], ...]:
        return tuple(
            row
            for row in self.events(code, start, end)
            if self._event_matches(node, row)
        )

    def _factor_matches(self, node: Mapping[str, Any], code: str, session: int) -> bool:
        if self._factor_provider is None:
            raise DslEvaluationError("factor DSL requires an as-of factor provider")
        observed = self._factor_provider(code, session, str(node["name"]))
        if observed is None or not isinstance(observed, (int, float)):
            return False
        target = node["value"]
        return {
            "lt": observed < target,
            "lte": observed <= target,
            "gt": observed > target,
            "gte": observed >= target,
            "eq": observed == target,
        }[node["comparison"]]

    def _eval(
        self,
        node: Mapping[str, Any],
        code: str,
        anchor: int,
        start: int,
        end: int,
    ) -> bool:
        op = node["op"]
        if op in {"signal", "trigger_mask"}:
            return bool(self._matching_rows(node, code, start, end))
        if op == "factor":
            return any(
                self._factor_matches(node, code, session)
                for session in range(max(1, start), end + 1)
            )
        if op == "and":
            return all(
                self._eval(child, code, anchor, start, end) for child in node["args"]
            )
        if op == "or":
            return any(
                self._eval(child, code, anchor, start, end) for child in node["args"]
            )
        if op == "not":
            return not self._eval(node["expr"], code, anchor, start, end)
        if op == "same_day":
            return self._eval(node["expr"], code, anchor, anchor, anchor)
        if op in {"within", "not_exists"}:
            # ``sessions`` is a maximum backward lag.  Evaluate the complete
            # child expression at each concrete session before folding the
            # window.  This keeps boolean children on one session and makes a
            # nested ``same_day`` relative to each lag rather than the outer
            # anchor only.
            lookback_start = anchor - int(node["sessions"])
            lookback_end = anchor if node["include_current"] else anchor - 1
            found = any(
                self._eval(node["expr"], code, session, session, session)
                for session in range(max(1, lookback_start), lookback_end + 1)
            )
            return not found if op == "not_exists" else found
        if op == "count":
            count_start = anchor - int(node["sessions"])
            count_end = anchor if node["include_current"] else anchor - 1
            roots = {
                self._relations.root_for_id(int(row["expected_model_id"]))
                for row in self._matching_rows(
                    node["expr"], code, count_start, count_end
                )
            }
            return int(node["min"]) <= len(roots) <= int(node["max"])
        if op == "sequence":
            gap = int(node["max_gap_sessions"])
            candidate_sessions: list[list[int]] = []
            for child in node["args"]:
                matches = [
                    session
                    for session in range(
                        max(1, anchor - gap * (len(node["args"]) - 1)), anchor + 1
                    )
                    if self._eval(child, code, session, session, session)
                ]
                candidate_sessions.append(matches)
            if node["anchor_last"]:
                candidate_sessions[-1] = [
                    session for session in candidate_sessions[-1] if session == anchor
                ]
            allow_same = bool(node["allow_same_session"])

            def search(position: int, previous: int | None) -> bool:
                if position == len(candidate_sessions):
                    return True
                for session in candidate_sessions[position]:
                    if previous is not None:
                        delta = session - previous
                        if delta < (0 if allow_same else 1) or delta > gap:
                            continue
                    if search(position + 1, session):
                        return True
                return False

            return search(0, None)
        raise DslEvaluationError(f"unsupported canonical op: {op}")

    def matches(self, combo: ComboDefinition, code: str, reveal_date: date) -> bool:
        anchor = self.session_for_date(reveal_date)
        # Root leaves are same-session by default. Temporal nodes widen only their
        # own subtree and can therefore never inspect a future session.
        return self._eval(combo.canonical["where"], code, anchor, anchor, anchor)


def make_combo(
    where: Mapping[str, Any],
    *,
    target_direction: int,
    relations: ModelRelations | None = None,
    action: str = "PREDICT_DIRECTION",
) -> ComboDefinition:
    """Compact constructor used by bounded candidate generation."""

    return ComboDefinition.from_value(
        {
            "dsl_version": DSL_VERSION,
            "action": action,
            "anchor": "reveal_date",
            "target_direction": target_direction,
            "where": where,
        },
        relations=relations,
    )
