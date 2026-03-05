import click
from QUANTAXIS.QASU.main import (
    QA_SU_save_etf_day,
    QA_SU_save_etf_list,
    QA_SU_save_etf_min
)

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
