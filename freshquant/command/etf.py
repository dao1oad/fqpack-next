import click
from QUANTAXIS.QASU.main import (
    QA_SU_save_etf_day,
    QA_SU_save_etf_list,
    QA_SU_save_etf_min,
)

from freshquant.data.etf_adj_sync import sync_etf_adj_all, sync_etf_xdxr_all


def _expand_codes(codes):
    expanded = []
    for code in codes or ():
        expanded.extend(
            item.strip() for item in str(code).split(",") if str(item).strip()
        )
    return expanded or None


@click.group(name="etf")
def etf_command_group():
    pass


@etf_command_group.command(name="save")
@click.option("-e", "--engine", type=str, default="tdx")
def etf_save_command(engine: str):
    try:
        QA_SU_save_etf_list(engine)
        QA_SU_save_etf_day(engine)
        QA_SU_save_etf_min(engine)
        sync_etf_xdxr_all()
        sync_etf_adj_all()
    except Exception as e:
        click.echo(f"Error saving etf: {str(e)}", err=True)


@click.group(name="etf.list")
def etf_list_command_group():
    pass


@etf_list_command_group.command(name="save")
@click.option("--engine", type=str, default="tdx")
def etf_list_save_command(engine):
    try:
        QA_SU_save_etf_list(engine)
    except Exception as e:
        click.echo(f"Error saving list: {str(e)}", err=True)

@click.group(name="etf.day")
def etf_day_command_group():
    pass


@etf_day_command_group.command(name="save")
@click.option("--engine", type=str, default="tdx")
def etf_day_save_command(engine):
    try:
        QA_SU_save_etf_day(engine)
    except Exception as e:
        click.echo(f"Error saving day: {str(e)}", err=True)

@click.group(name="etf.min")
def etf_min_command_group():
    pass


@etf_min_command_group.command(name="save")
@click.option("--engine", type=str, default="tdx")
def etf_min_save_command(engine):
    try:
        QA_SU_save_etf_min(engine)
    except Exception as e:
        click.echo(f"Error saving min: {str(e)}", err=True)


@click.group(name="etf.xdxr")
def etf_xdxr_command_group():
    pass


@etf_xdxr_command_group.command(name="save")
@click.option("--code", "codes", multiple=True, help="ETF code, supports repeat/comma")
def etf_xdxr_save_command(codes):
    try:
        sync_etf_xdxr_all(codes=_expand_codes(codes))
    except Exception as e:
        click.echo(f"Error saving etf xdxr: {str(e)}", err=True)


@click.group(name="etf.adj")
def etf_adj_command_group():
    pass


@etf_adj_command_group.command(name="save")
@click.option("--code", "codes", multiple=True, help="ETF code, supports repeat/comma")
def etf_adj_save_command(codes):
    try:
        sync_etf_adj_all(codes=_expand_codes(codes))
    except Exception as e:
        click.echo(f"Error saving etf adj: {str(e)}", err=True)
