import json

import click
from QUANTAXIS.QASU.index_compat import migrate_canonical_indexes
from QUANTAXIS.QASU.main import (
    QA_SU_save_index_day,
    QA_SU_save_index_list,
    QA_SU_save_index_min,
)
from QUANTAXIS.QAUtil import DATABASE


@click.group(name="index")
def index_command_group():
    pass


@index_command_group.command(name="save")
@click.option("-e", "--engine", type=str, default="tdx")
def index_save_command(engine: str):
    try:
        QA_SU_save_index_list(engine)
        QA_SU_save_index_day(engine)
        QA_SU_save_index_min(engine)
    except Exception as e:
        click.echo(f"Error saving index: {str(e)}", err=True)


@index_command_group.command(name="migrate-indexes")
@click.option("--dry-run", is_flag=True, help="Inspect the canonical index migration.")
@click.option("--execute", is_flag=True, help="Apply the canonical index migration.")
def index_migrate_indexes_command(dry_run: bool, execute: bool):
    if dry_run == execute:
        raise click.UsageError("必须且只能提供 --dry-run 或 --execute 其中之一")

    report = migrate_canonical_indexes(DATABASE, execute=execute)
    click.echo(json.dumps(report, ensure_ascii=False))
    if execute and not report["ok"]:
        raise click.ClickException(
            "canonical index migration blocked by duplicate keys"
        )


@click.group(name="index.list")
def index_list_command_group():
    pass


@index_list_command_group.command(name="save")
@click.option("--engine", type=str, default="tdx")
def index_list_save_command(engine):
    try:
        QA_SU_save_index_list(engine)
    except Exception as e:
        click.echo(f"Error saving list: {str(e)}", err=True)


@click.group(name="index.day")
def index_day_command_group():
    pass


@index_day_command_group.command(name="save")
@click.option("--engine", type=str, default="tdx")
def index_day_save_command(engine):
    try:
        QA_SU_save_index_day(engine)
    except Exception as e:
        click.echo(f"Error saving day: {str(e)}", err=True)


@click.group(name="index.min")
def index_min_command_group():
    pass


@index_min_command_group.command(name="save")
@click.option("--engine", type=str, default="tdx")
def index_min_save_command(engine):
    try:
        QA_SU_save_index_min(engine)
    except Exception as e:
        click.echo(f"Error saving min: {str(e)}", err=True)
