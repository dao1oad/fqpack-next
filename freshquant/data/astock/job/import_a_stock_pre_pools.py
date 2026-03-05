# -*- coding:utf-8 -*-

import codecs

import click
import pydash

from freshquant.config import settings
from freshquant.db import DBfreshquant
from freshquant.signal.a_stock_common import save_a_stock_pre_pools


def run(file, category):
    with codecs.open(file, 'r', 'utf-8') as input_file:
        lines = input_file.readlines()
        codes = (
            pydash.chain(lines)
            .map(lambda line: line.strip())
            .filter_(lambda line: len(line) > 0)
            .map(lambda line: line[-6:])
            .value()
        )
        for code in codes:
            save_a_stock_pre_pools(code, category)


@click.command()
@click.option('--file', type=str, required=True)
@click.option('--category', type=str, required=True)
def main(file, category):
    run(file, category)


if __name__ == "__main__":
    main()
