# -*- coding: utf-8 -*-

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence


def find_exit_allocation_integrity_errors(
    *,
    position_entries: Sequence[Mapping[str, Any]],
    entry_slices: Sequence[Mapping[str, Any]],
    exit_allocations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    entries = [dict(item) for item in list(position_entries or [])]
    slices = [dict(item) for item in list(entry_slices or [])]
    allocations = [dict(item) for item in list(exit_allocations or [])]
    errors: list[dict[str, Any]] = []

    entry_by_id = _unique_documents(
        entries,
        identity_field="entry_id",
        duplicate_reference_type="duplicate_entry_id",
        errors=errors,
    )
    slice_by_id = _unique_documents(
        slices,
        identity_field="entry_slice_id",
        duplicate_reference_type="duplicate_entry_slice_id",
        errors=errors,
    )
    _unique_documents(
        allocations,
        identity_field="allocation_id",
        duplicate_reference_type="duplicate_allocation_id",
        errors=errors,
    )

    allocated_by_entry: Counter[str] = Counter()
    allocated_by_slice: Counter[str] = Counter()
    for allocation in allocations:
        allocation_id = _normalize_text(allocation.get("allocation_id"))
        entry_id = _normalize_text(allocation.get("entry_id"))
        slice_id = _normalize_text(allocation.get("entry_slice_id"))
        entry = entry_by_id.get(entry_id)
        slice_document = slice_by_id.get(slice_id)

        if entry is None:
            errors.append(
                _reference_error(
                    allocation_id=allocation_id,
                    reference_type="entry_id",
                    reference_id=entry_id,
                )
            )
        if slice_document is None:
            errors.append(
                _reference_error(
                    allocation_id=allocation_id,
                    reference_type="entry_slice_id",
                    reference_id=slice_id,
                )
            )
        if entry is not None and slice_document is not None:
            slice_entry_id = _normalize_text(slice_document.get("entry_id"))
            if slice_entry_id != entry_id:
                errors.append(
                    {
                        **_reference_error(
                            allocation_id=allocation_id,
                            reference_type="entry_slice_owner",
                            reference_id=slice_id,
                        ),
                        "expected_entry_id": entry_id,
                        "actual_entry_id": slice_entry_id,
                    }
                )
            entry_symbol = _normalize_text(entry.get("symbol"))
            slice_symbol = _normalize_text(slice_document.get("symbol"))
            if entry_symbol and slice_symbol and entry_symbol != slice_symbol:
                errors.append(
                    {
                        **_reference_error(
                            allocation_id=allocation_id,
                            reference_type="entry_slice_symbol",
                            reference_id=slice_id,
                        ),
                        "expected_symbol": entry_symbol,
                        "actual_symbol": slice_symbol,
                    }
                )

        allocation_symbol = _normalize_text(allocation.get("symbol"))
        for reference_type, document in (
            ("allocation_entry_symbol", entry),
            ("allocation_entry_slice_symbol", slice_document),
        ):
            document_symbol = _normalize_text((document or {}).get("symbol"))
            if (
                allocation_symbol
                and document_symbol
                and allocation_symbol != document_symbol
            ):
                errors.append(
                    {
                        **_reference_error(
                            allocation_id=allocation_id,
                            reference_type=reference_type,
                            reference_id=entry_id if document is entry else slice_id,
                        ),
                        "expected_symbol": document_symbol,
                        "actual_symbol": allocation_symbol,
                    }
                )

        allocated_quantity = _positive_int(allocation.get("allocated_quantity"))
        if allocated_quantity is None:
            errors.append(
                {
                    **_reference_error(
                        allocation_id=allocation_id,
                        reference_type="allocated_quantity",
                        reference_id=allocation_id,
                    ),
                    "actual_quantity": allocation.get("allocated_quantity"),
                }
            )
            continue
        if entry_id:
            allocated_by_entry[entry_id] += allocated_quantity
        if slice_id:
            allocated_by_slice[slice_id] += allocated_quantity

    errors.extend(
        _quantity_conservation_errors(
            documents=entries,
            identity_field="entry_id",
            actual_by_identity=allocated_by_entry,
            reference_type="entry_allocation_quantity",
        )
    )
    errors.extend(
        _quantity_conservation_errors(
            documents=slices,
            identity_field="entry_slice_id",
            actual_by_identity=allocated_by_slice,
            reference_type="entry_slice_allocation_quantity",
        )
    )
    return sorted(errors, key=_error_sort_key)


def summarize_integrity_errors(errors):
    """Group integrity errors by symbol (both sides of a mismatch) and summarize."""

    normalized_errors = list(errors or [])
    by_symbol = {}
    for error in normalized_errors:
        symbols = {
            _normalize_text(error.get("expected_symbol")),
            _normalize_text(error.get("actual_symbol")),
        }
        symbols.discard(None)
        for symbol in symbols:
            by_symbol[symbol] = by_symbol.get(symbol, 0) + 1
    return {
        "ok": len(normalized_errors) == 0,
        "error_count": len(normalized_errors),
        "errors": normalized_errors,
        "by_symbol": by_symbol,
    }


def _unique_documents(
    documents,
    *,
    identity_field,
    duplicate_reference_type,
    errors,
):
    result = {}
    for document in documents:
        identity = _normalize_text(document.get(identity_field))
        if not identity:
            errors.append(
                _reference_error(
                    allocation_id=(
                        _normalize_text(document.get("allocation_id"))
                        if identity_field != "allocation_id"
                        else None
                    ),
                    reference_type=identity_field,
                    reference_id=None,
                )
            )
            continue
        if identity in result:
            errors.append(
                _reference_error(
                    allocation_id=(
                        identity if identity_field == "allocation_id" else None
                    ),
                    reference_type=duplicate_reference_type,
                    reference_id=identity,
                )
            )
            continue
        result[identity] = document
    return result


def _quantity_conservation_errors(
    *,
    documents,
    identity_field,
    actual_by_identity,
    reference_type,
):
    errors = []
    for document in documents:
        identity = _normalize_text(document.get(identity_field))
        original = _nonnegative_int(document.get("original_quantity"))
        remaining = _nonnegative_int(document.get("remaining_quantity"))
        if not identity or original is None or remaining is None:
            continue
        if remaining > original:
            errors.append(
                {
                    **_reference_error(
                        allocation_id=None,
                        reference_type=f"{identity_field}_quantity_bounds",
                        reference_id=identity,
                    ),
                    "original_quantity": original,
                    "remaining_quantity": remaining,
                }
            )
            continue
        expected = original - remaining
        actual = int(actual_by_identity.get(identity, 0))
        if expected != actual:
            errors.append(
                {
                    **_reference_error(
                        allocation_id=None,
                        reference_type=reference_type,
                        reference_id=identity,
                    ),
                    "expected_quantity": expected,
                    "actual_quantity": actual,
                }
            )
    return errors


def _reference_error(*, allocation_id, reference_type, reference_id):
    return {
        "allocation_id": allocation_id,
        "reference_type": reference_type,
        "reference_id": reference_id,
    }


def _positive_int(value):
    normalized = _exact_int(value)
    return normalized if normalized is not None and normalized > 0 else None


def _nonnegative_int(value):
    normalized = _exact_int(value)
    return normalized if normalized is not None and normalized >= 0 else None


def _exact_int(value):
    try:
        normalized = int(value)
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if normalized != numeric:
        return None
    return normalized


def _normalize_text(value):
    if value in (None, "", "None"):
        return None
    normalized = str(value).strip()
    return normalized or None


def _error_sort_key(error):
    return (
        error.get("allocation_id") is None,
        str(error.get("allocation_id") or ""),
        str(error.get("reference_type") or ""),
        str(error.get("reference_id") or ""),
    )


__all__ = ["find_exit_allocation_integrity_errors", "summarize_integrity_errors"]
