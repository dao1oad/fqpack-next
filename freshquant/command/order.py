import click
from bson import ObjectId
from rich.console import Console
from rich.padding import Padding
from rich.table import Table

from freshquant.db import DBfreshquant
from freshquant.instrument.general import query_instrument_info
from freshquant.order_management.time_helpers import (
    beijing_datetime_from_epoch,
    beijing_epoch_range_for_date,
    normalize_cli_date_input,
)
from freshquant.util.xtquant import (  # 导入 translate_broker_price_type 函数
    translate_broker_price_type,
    translate_order_type,
)


@click.group(name="xt-order")
def xt_order_command_group():
    pass


@xt_order_command_group.command(name="list")
@click.option(
    "--code", required=False, help="Filter by stock code (e.g., 300888 or 300888.SZ)"
)
@click.option(
    "--date",
    required=False,
    help="Filter by date (e.g., YYYYMMDD, YYYY.MM.DD, or YYYY-MM-DD)",
)
@click.option(
    "--fields",
    required=False,
    help="Comma-separated list of fields to display (e.g., id,stock_code,traded_price)",
)
def xt_order_list_command(code: str, date: str, fields: str):
    list_xt_order(code, date, fields)


@xt_order_command_group.command(name="rm")
@click.option("--id", required=False, help="The ID of the record to delete")
@click.option(
    "--code",
    required=False,
    help="Delete records by stock code (e.g., 300888 or 300888.SZ)",
)
def xt_order_rm_command(id: str, code: str):
    """Delete a record by its ID or stock code and display the remaining records."""
    query = {}

    if id:
        try:
            # Convert the input string ID to ObjectId
            object_id = ObjectId(id)
            query["_id"] = object_id
        except Exception as e:
            click.echo(f"Invalid ID format: {e}")
            return

    if code:
        # Normalize the code by removing the suffix (e.g., ".SZ" or ".SH") if present
        normalized_code = code.split(".")[0]
        query["stock_code"] = {
            "$regex": f"^{normalized_code}(\\..*)?$",
            "$options": "i",
        }

    if not query:
        click.echo("Either --id or --code must be provided.")
        return

    deleted_count = DBfreshquant["xt_orders"].delete_many(query).deleted_count
    if deleted_count > 0:
        click.echo(f"Deleted {deleted_count} record(s).")
    else:
        click.echo("No records were deleted.")


def list_xt_order(code: str = None, date: str = None, fields: str = None):
    query = {}
    if code:
        # Normalize the code by removing the suffix (e.g., ".SZ" or ".SH") if present
        normalized_code = code.split(".")[0]
        query["stock_code"] = {
            "$regex": f"^{normalized_code}(\\..*)?$",
            "$options": "i",
        }

    if date:
        # Normalize the date format to YYYY-MM-DD
        try:
            normalized_date = normalize_cli_date_input(date)
            start_ts, end_ts = beijing_epoch_range_for_date(normalized_date)
            # Add the date filter to the query
            query["order_time"] = {
                "$gte": start_ts,
                "$lt": end_ts,
            }
        except Exception as e:
            click.echo(f"Error parsing date: {e}")
            return

    records = list(DBfreshquant["xt_orders"].find(query).sort([('order_time', 1)]))

    # Default fields to display if not specified
    default_fields = [
        "id",
        "account_id",
        "stock_code",
        "name",
        "order_id",
        "order_type",
        "price",
        "order_volume",
        "traded_price",
        "traded_volume",
        "order_time",
        "strategy_name",
        "source",
        "price_type",  # 添加 price_type 字段
    ]

    # Parse the fields option
    selected_fields = fields.split(",") if fields else default_fields

    # Create a Rich Table with borders
    table = Table(
        show_header=True,
        header_style="bold magenta",
        show_lines=True,
        title="委托记录",
        title_style="bold",
    )

    # Define all possible columns with their styles
    column_definitions = {
        "id": {"style": "dim", "overflow": "fold"},
        "account_id": {"overflow": "fold"},
        "stock_code": {"overflow": "fold"},
        "name": {"overflow": "fold"},
        "order_id": {"justify": "right", "overflow": "fold"},
        "order_type": {"justify": "right", "overflow": "fold"},
        "price": {"justify": "right", "overflow": "fold"},
        "order_volume": {"justify": "right", "overflow": "fold"},
        "traded_price": {"justify": "right", "overflow": "fold"},
        "traded_volume": {"justify": "right", "overflow": "fold"},
        "order_time": {"overflow": "fold"},
        "strategy_name": {"overflow": "fold"},
        "source": {"overflow": "fold"},
        "price_type": {
            "justify": "right",
            "overflow": "fold",
        },  # 新增 price_type 列定义
    }

    # Add only the selected fields as columns
    for field in selected_fields:
        if field in column_definitions:
            table.add_column(field, **column_definitions[field])

    for record in records:
        row_data = []

        for field in selected_fields:
            if field == "id":
                row_data.append(str(record.get('_id', "")))
            elif field == "account_id":
                account_id = str(record.get('account_id'))
                masked_account_id = (
                    lambda x: (
                        x[: len(x) // 3]
                        + '*' * (len(x) // 3)
                        + x[-(len(x) - 2 * (len(x) // 3)) :]
                        if len(x) >= 3
                        else x
                    )
                )(str(account_id))
                row_data.append(masked_account_id)
            elif field == "order_type":
                order_type = record.get('order_type')
                order_type_desc = translate_order_type(order_type)
                row_data.append(order_type_desc)
            elif field == "price":
                row_data.append(f"{round(record.get('price', 0), 2):.2f}")
            elif field == "order_volume":
                row_data.append(f"{record.get('order_volume', 0)}")
            elif field == "traded_price":
                row_data.append(f"{round(record.get('traded_price', 0), 2):.2f}")
            elif field == "traded_volume":
                row_data.append(f"{record.get('traded_volume', 0)}")
            elif field == "order_time":
                order_time = record.get('order_time')
                if order_time:
                    order_time = beijing_datetime_from_epoch(order_time).strftime(
                        '%Y-%m-%d %H:%M:%S'
                    )
                else:
                    order_time = "N/A"
                row_data.append(order_time)
            elif field in ["stock_code", "order_id", "strategy_name", "source"]:
                row_data.append(str(record.get(field, "")))
            elif field == "name":
                stock_code = record.get('stock_code')
                if stock_code:
                    stock_info = query_instrument_info(stock_code)
                    stock_name = (
                        stock_info.get('name', 'Unknown') if stock_info else 'Unknown'
                    )
                else:
                    stock_name = 'Unknown'
                row_data.append(stock_name)
            elif field == "price_type":
                price_type = record.get('price_type')
                price_type_desc = translate_broker_price_type(price_type)
                row_data.append(price_type_desc)
            else:
                row_data.append("")  # For fields that don't exist

        # Add rows to the table
        table.add_row(*row_data)

    # Print the table using Rich Console with expanded width
    console = Console()  # Set a wider console width
    t = Padding(table, (1, 0, 0, 0))
    console.print(t)


# Entry point to run tests
if __name__ == "__main__":
    xt_order_command_group()
