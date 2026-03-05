# -*- coding: utf-8 -*-

import click

from freshquant.rear import api_server


@click.group()
def run():
    pass

@run.command("api-server")
@click.option('--port', type=int, default=5000)
def run_api_server(port):
    api_server.run(port)
