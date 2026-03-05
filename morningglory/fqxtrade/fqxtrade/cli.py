# -*- coding: utf-8 -*-

import click

from fqxtrade.xtquant.cli_commands import xtquant


@click.group()
def commands():
    pass


def main():
    commands.add_command(xtquant)
    commands()


if __name__ == "__main__":
    main()
