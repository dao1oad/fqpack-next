import click
from QUANTAXIS.QASU.main import (
    QA_SU_save_index_day,
    QA_SU_save_index_list,
    QA_SU_save_index_min,
)

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