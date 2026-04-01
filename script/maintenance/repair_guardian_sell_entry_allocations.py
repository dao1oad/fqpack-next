from __future__ import annotations

import json
from pathlib import Path
import sys

import click

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from freshquant.order_management.db import get_order_management_db
from freshquant.order_management.repair.guardian_sell_allocation import (
    repair_guardian_sell_allocations,
)


def _get_database():
    return get_order_management_db()


def run_repair(
    *,
    execute=False,
    symbol=None,
    symbols=None,
    backup_dir=None,
    database=None,
):
    database = database if database is not None else _get_database()
    normalized_symbols = [
        item
        for item in [
            _normalize_optional_text(symbol),
            *(_normalize_symbol_list(symbols)),
        ]
        if item
    ]
    return repair_guardian_sell_allocations(
        database=database,
        symbols=normalized_symbols or None,
        execute=bool(execute),
        backup_dir=_normalize_optional_text(backup_dir),
    )


@click.command(name="repair-guardian-sell-entry-allocations")
@click.option("--execute", is_flag=True, help="Apply the repair to the database.")
@click.option("--symbol", default=None, help="Repair a single symbol.")
@click.option(
    "--symbols",
    default=None,
    help="Comma-separated symbol list; defaults to all strategy-sell symbols.",
)
@click.option(
    "--backup-dir",
    default=None,
    help="Optional artifact directory for per-symbol JSON backups.",
)
def repair_guardian_sell_entry_allocations_command(
    execute,
    symbol,
    symbols,
    backup_dir,
):
    summary = run_repair(
        execute=execute,
        symbol=symbol,
        symbols=symbols,
        backup_dir=backup_dir,
    )
    click.echo(json.dumps(summary, ensure_ascii=False))


def _normalize_optional_text(value):
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_symbol_list(value):
    text = _normalize_optional_text(value)
    if text is None:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def main():
    repair_guardian_sell_entry_allocations_command()


if __name__ == "__main__":
    main()
