# -*- coding: utf-8 -*-

"""#597 PR-2：broker_only 订单非法携带 correlation token 的受控修复。

背景：broker_only 订单（XT 回报无内部归属，``source_type=broker_only``）的归属语义
不允许携带 ``broker_correlation_token``（token 指向真实下单机的内部订单；
``_classify_broker_order_owner`` 会抛 ``BrokerIdentityConflict``，后续任何 claim
都会失败）。2026-08-11 人工修复（fix_token）把 token 写入 broker_only 文档，
造成非法态；本脚本将其恢复为合法态（$unset token），写前审计留痕。

用法：
    python script/maintenance/repair_broker_only_correlation_token.py --dry-run
    python script/maintenance/repair_broker_only_correlation_token.py --execute [--backup-db fqom_bak_xxx]
"""

import click

from freshquant.order_management.db import get_order_management_db


def _collect_violations(database):
    """收集 broker_only 且携带非空 correlation token 的文档（非法态）。"""

    violations = []
    for doc in database["om_broker_orders"].find({}):
        if str(doc.get("source_type") or "").strip().lower() != "broker_only":
            continue
        token = doc.get("broker_correlation_token")
        if token is None or str(token).strip() == "":
            continue
        violations.append(
            {
                "broker_order_key": doc.get("broker_order_key"),
                "internal_order_id": doc.get("internal_order_id"),
                "broker_correlation_token": token,
                "updated_at": doc.get("updated_at"),
            }
        )
    return violations


def _record_execute_audit_start(*, counts, backup_db) -> str:
    """写前审计（#583 schema）：任何写入前先落 started 记录。

    #597 PR-2：审计为修复前置（fail-closed）——审计写失败即中止，
    不允许在无痕状态下执行写库。
    """

    import socket
    from datetime import datetime, timezone
    from uuid import uuid4

    try:
        from freshquant.db import DBfreshquant

        audit_id = f"audit_{uuid4().hex}"
        DBfreshquant["audit_log"].insert_one(
            {
                "audit_id": audit_id,
                "operation": "maintenance_repair_broker_only_correlation_token",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "host": socket.gethostname(),
                "counts": {"broker_only_tokens": len(counts)},
                "violations": [
                    {
                        "broker_order_key": item.get("broker_order_key"),
                        "broker_correlation_token": item.get(
                            "broker_correlation_token"
                        ),
                        "updated_at": item.get("updated_at"),
                    }
                    for item in counts
                ],
                "backup_db": backup_db,
                "status": "started",
            }
        )
        return audit_id
    except Exception as exc:  # pragma: no cover - 防御降级
        raise click.ClickException(f"audit write failed; aborting: {exc}")


def _record_execute_audit_complete(audit_id, *, verify: str) -> None:
    if not audit_id:
        return
    try:
        from datetime import datetime, timezone

        from freshquant.db import DBfreshquant

        DBfreshquant["audit_log"].update_one(
            {"audit_id": audit_id},
            {
                "$set": {
                    "status": "completed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "verify": verify,
                }
            },
        )
    except Exception as exc:  # pragma: no cover - 防御降级
        click.echo(f"warning: audit complete write failed: {exc}")


def _backup_broker_orders(database, backup_db):
    target = database.client[str(backup_db).strip()]
    documents = list(database["om_broker_orders"].find({}))
    target["om_broker_orders"].delete_many({})
    if documents:
        target["om_broker_orders"].insert_many(documents, ordered=False)
    click.echo(f"backup om_broker_orders -> {backup_db}: {len(documents)} docs")


def _apply_repairs(database, violations):
    for item in violations:
        database["om_broker_orders"].update_one(
            {
                # B3：collect→apply 间防 TOCTOU——仅命中同一 broker_only 文档
                "broker_order_key": item["broker_order_key"],
                "source_type": "broker_only",
                "broker_correlation_token": item["broker_correlation_token"],
            },
            {"$unset": {"broker_correlation_token": ""}},
        )


@click.command()
@click.option("--dry-run", "dry_run", is_flag=True, default=False)
@click.option("--execute", "execute", is_flag=True, default=False)
@click.option("--backup-db", type=str, default=None)
def main(*, dry_run, execute, backup_db):
    if not dry_run and not execute:
        dry_run = True
    if dry_run and execute:
        raise click.UsageError("choose either --dry-run or --execute, not both")

    database = get_order_management_db()
    violations = _collect_violations(database)
    click.echo(
        f"broker_only correlation token violations: {len(violations)} "
        f"mode={'execute' if execute else 'dry-run'}"
    )
    for item in violations:
        click.echo(
            f"  {item['broker_order_key']} "
            f"token={item['broker_correlation_token']} "
            f"updated_at={item['updated_at']}"
        )
    if not execute:
        click.echo("dry-run complete; no writes performed")
        return

    audit_id = _record_execute_audit_start(
        counts=violations,
        backup_db=backup_db,
    )
    if backup_db:
        _backup_broker_orders(database, backup_db)
    _apply_repairs(database, violations)

    remaining = _collect_violations(database)
    verify = f"remaining_violations={len(remaining)}"
    click.echo(f"repair verify: {verify}")
    _record_execute_audit_complete(audit_id, verify=verify)
    if remaining:
        raise click.ClickException(
            f"{len(remaining)} violations remain after repair; verify required"
        )
    click.echo("repair complete")


if __name__ == "__main__":
    main()
