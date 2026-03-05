import click
from QUANTAXIS.QASU.main import (
    QA_SU_save_bond_day,
    QA_SU_save_bond_list,
    QA_SU_save_bond_min
)
from freshquant.trade.trade import do_reverse_repo

@click.group(name="bond")
def bond_command_group():
    pass

@bond_command_group.command(name="save")
def bond_save_command():
    try:
        QA_SU_save_bond_list()
        QA_SU_save_bond_day()
        QA_SU_save_bond_min()
    except Exception as e:
        click.echo(f"Error saving bond: {str(e)}", err=True)

@click.group(name="bond.list")
def bond_list_command_group():
    pass

@bond_list_command_group.command(name="save")
@click.option("--engine", type=str, default="tdx")
def bond_list_save_command(engine):
    try:
        QA_SU_save_bond_list(engine)
    except Exception as e:
        click.echo(f"Error saving list: {str(e)}", err=True)

@click.group(name="bond.day")
def bond_day_command_group():
    pass

@bond_day_command_group.command(name="save")
@click.option("--engine", type=str, default="tdx")
def bond_day_save_command(engine):
    try:
        QA_SU_save_bond_day(engine)
    except Exception as e:
        click.echo(f"Error saving day: {str(e)}", err=True)

@click.group(name="bond.min")
def bond_min_command_group():
    pass

@bond_min_command_group.command(name="save")
@click.option("--engine", type=str, default="tdx")
def bond_min_save_command(engine):
    try:
        QA_SU_save_bond_min(engine)
    except Exception as e:
        click.echo(f"Error saving min: {str(e)}", err=True)

@bond_command_group.command(name="do")
@click.argument("arg", nargs=1)
def bond_command_do(arg: str):
    if arg == "reverse-repo":
        do_reverse_repo()
    else:
        click.echo("Not implemented yet")