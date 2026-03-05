import pendulum
from dagster import op

from freshquant.data.clean import clean_db


@op
def op_clean_db():
    clean_db()
    return pendulum.now().format("YYYY-MM-DD hh:mm:ss")
