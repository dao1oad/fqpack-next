import click

from freshquant.signal import futureChanlunMonitor


@click.group()
def monitor():
    pass


@monitor.command(name="future")
@click.option('--loop/--no-loop', default=True)
def monitor_future(**kwargs):
    futureChanlunMonitor.run(**kwargs)
