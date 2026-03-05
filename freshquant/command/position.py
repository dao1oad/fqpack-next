import click
from bson import ObjectId
from freshquant.db import DBfreshquant
from rich.table import Table
from rich.console import Console
from rich.padding import Padding
from freshquant.instrument.general import query_instrument_info
import pyperclip

@click.group(name="xt-position")
def xt_position_command_group():
    pass

@xt_position_command_group.command(name="list")
@click.option("--code", required=False, help="Filter by stock code (e.g., 300888 or 300888.SZ)")
@click.option("--account", required=False, help="Filter by account ID")
@click.option("--fields", required=False, help="Comma-separated list of fields to display (e.g., id,stock_code,avg_price)")
def xt_position_list_command(code: str, account: str, fields: str):
    list_xt_position(code, account, fields)

@xt_position_command_group.command(name="rm")
@click.option("--id", required=False, help="The ID of the record to delete")
@click.option("--code", required=False, help="Delete records by stock code (e.g., 300888 or 300888.SZ)")
def xt_position_rm_command(id: str, code: str):
    """Delete a record by its ID or stock code and display the remaining records."""
    query = {}

    if id:
        try:
            object_id = ObjectId(id)
            query["_id"] = object_id
        except Exception as e:
            click.echo(f"Invalid ID format: {e}")
            return

    if code:
        normalized_code = code.split(".")[0]
        query["stock_code"] = {"$regex": f"^{normalized_code}(\\..*)?$", "$options": "i"}

    if not query:
        click.echo("Either --id or --code must be provided.")
        return

    deleted_count = DBfreshquant["xt_positions"].delete_many(query).deleted_count
    if deleted_count > 0:
        click.echo(f"Deleted {deleted_count} record(s).")
    else:
        click.echo("No records were deleted.")

@xt_position_command_group.command(name="copy")
@click.option("--code", required=False, help="Filter by stock code (e.g., 300888 or 300888.SZ)")
@click.option("--account", required=False, help="Filter by account ID")
def xt_position_copy_command(code: str, account: str):
    """Copy the filtered positions to the clipboard."""
    query = {}
    
    if code:
        normalized_code = code.split(".")[0]
        query["stock_code"] = {"$regex": f"^{normalized_code}(\\..*)?$", "$options": "i"}
    
    if account:
        query["account_id"] = account
    
    records = list(DBfreshquant["xt_positions"].find(query).sort([('_id', 1)]))
    
    if not records:
        click.echo("No records found.")
        return
    
    # Extract stock codes from the records and remove the suffix
    stock_codes = [record.get('stock_code').split('.')[0] for record in records]
    copied_text = "\n".join(stock_codes)
    
    pyperclip.copy(copied_text)
    click.echo(f"Copied {len(stock_codes)} stock code(s) to clipboard: \n{copied_text}")

def list_xt_position(code: str = None, account: str = None, fields: str = None):
    query = {}
    if code:
        normalized_code = code.split(".")[0]
        query["stock_code"] = {"$regex": f"^{normalized_code}(\\..*)?$", "$options": "i"}
    
    if account:
        query["account_id"] = account
    
    records = list(DBfreshquant["xt_positions"].find(query).sort([('_id', 1)]))
    
    default_fields = [
        "id", "account_id", "stock_code", "name", "avg_price", "volume",
        "market_value", "frozen_volume", "can_use_volume", "source"
    ]
    
    selected_fields = fields.split(",") if fields else default_fields
    
    table = Table(show_header=True, header_style="bold magenta", show_lines=True, title="持仓记录", title_style="bold")
    
    column_definitions = {
        "id": {"style": "dim", "overflow": "fold"},
        "account_id": {"overflow": "fold"},
        "stock_code": {"overflow": "fold"},
        "name": {"overflow": "fold"},
        "avg_price": {"justify": "right", "overflow": "fold"},
        "volume": {"justify": "right", "overflow": "fold"},
        "market_value": {"justify": "right", "overflow": "fold"},
        "frozen_volume": {"justify": "right", "overflow": "fold"},
        "can_use_volume": {"justify": "right", "overflow": "fold"},
        "source": {"overflow": "fold"}
    }
    
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
                masked_account_id = (lambda x: x[:len(x)//3] + '*'*(len(x)//3) + x[-(len(x)-2*(len(x)//3)):] if len(x) >= 3 else x)(str(account_id))
                row_data.append(masked_account_id)
            elif field == "avg_price":
                row_data.append(f"{round(record.get('avg_price', 0), 2):.2f}")
            elif field == "volume":
                row_data.append(f"{record.get('volume', 0)}")
            elif field == "market_value":
                row_data.append(f"{round(record.get('market_value', 0), 2):.2f}")
            elif field == "frozen_volume":
                row_data.append(f"{record.get('frozen_volume', 0)}")
            elif field == "can_use_volume":
                row_data.append(f"{record.get('can_use_volume', 0)}")
            elif field in ["stock_code", "source"]:
                row_data.append(str(record.get(field, "")))
            elif field == "name":
                stock_code = record.get('stock_code')
                if stock_code:
                    stock_info = query_instrument_info(stock_code)
                    stock_name = stock_info.get('name', 'Unknown') if stock_info else 'Unknown'
                else:
                    stock_name = 'Unknown'
                row_data.append(stock_name)
            else:
                row_data.append("")
        
        table.add_row(*row_data)
    
    console = Console()
    t = Padding(table, (1, 0, 0, 0))
    console.print(t)

if __name__ == "__main__":
    xt_position_command_group()
