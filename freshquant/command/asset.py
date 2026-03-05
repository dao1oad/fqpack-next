import click
from bson import ObjectId
from freshquant.db import DBfreshquant
from rich.table import Table
from rich.console import Console
from rich.padding import Padding
from freshquant.util.xtquant import translate_account_type

@click.group(name="xt-asset")
def xt_asset_command_group():
    pass

@xt_asset_command_group.command(name="list")
def asset_list_command():
    list_asset()

@xt_asset_command_group.command(name="rm")
@click.option("--id", required=True, help="The ID of the record to delete")
def asset_rm_command(id: str):
    """Delete a record by its ID and display the remaining records."""
    try:
        # Convert the input string ID to ObjectId
        object_id = ObjectId(id)
    except Exception as e:
        click.echo(f"Invalid ID format: {e}")
        return

    deleted_count = DBfreshquant["xt_assets"].delete_one({"_id": object_id}).deleted_count
    if deleted_count > 0:
        click.echo(f"Deleted {deleted_count} record(s).")
    else:
        click.echo("No records were deleted.")
    
    # List the remaining assets
    list_asset()

def list_asset():
    records = list(DBfreshquant["xt_assets"].find().sort([('account_id', 1)]))
    
    # Create a Rich Table
    table = Table(show_header=True, header_style="bold magenta", show_lines=True, title="资产概况", title_style="bold")
    table.add_column("id", style="dim", overflow="fold")
    table.add_column("account_id", overflow="fold")
    table.add_column("account_type", overflow="fold")
    table.add_column("cash", justify="right", overflow="fold")
    table.add_column("frozen_cash", justify="right", overflow="fold")
    table.add_column("market_value", justify="right", overflow="fold")
    table.add_column("position_pct", justify="right", overflow="fold")
    table.add_column("source", overflow="fold")
    table.add_column("total_asset", justify="right", overflow="fold")
    
    for record in records:
        # Mask account_id by hiding the middle 4 digits
        account_id = str(record.get('account_id'))
        masked_account_id = (lambda x: x[:len(x)//3] + '*'*(len(x)//3) + x[-(len(x)-2*(len(x)//3)):] if len(x) >= 3 else x)(str(account_id))

        # Translate account_type using the common function
        account_type = record.get('account_type')
        account_type_desc = translate_account_type(account_type)
        
        # Add rows to the table
        table.add_row(
            str(record.get('_id')),  # Ensure _id is converted to string
            masked_account_id,       # Use masked account_id
            account_type_desc,       # Use translated account_type
            f"{round(record.get('cash'), 2):.2f}",  # Round cash to 2 decimal places
            f"{round(record.get('frozen_cash'), 2):.2f}",  # Round frozen_cash to 2 decimal places
            f"{record.get('market_value'):.2f}",
            f"{round(record.get('position_pct'), 2):.2f}%",  # Round position_pct to 2 decimal places
            record.get('source'),
            f"{round(record.get('total_asset'), 2):.2f}"  # Round total_asset to 2 decimal places
        )
    
    # Print the table using Rich Console with expanded width
    console = Console()  # Set a wider console width
    t = Padding(table, (1, 0, 0, 0))  # Add padding to the table
    console.print(t)



# Entry point to run tests
if __name__ == "__main__":
    xt_asset_command_group()
