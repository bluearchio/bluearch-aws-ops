from rich.table import Table
from rich.console import Console, Group
from rich.text import Text
from rich.panel import Panel
import sys
from termcolor import colored
from rich.prompt import Prompt
import re
import boto3
# Ensure console can handle UTF-8 characters
sys.stdout.reconfigure(encoding='utf-8')
console = Console()

def display_accounts_and_regions(accounts_and_regions_dict):
    table = Table(show_header=True, header_style="bold magenta", show_lines=True)
    table.add_column("Account ID", style="dim")
    table.add_column("Account Name", style="dim")
    table.add_column("Region Names", justify="left")

    for account_id, account_info in accounts_and_regions_dict.items():
        account_name = account_info['account_name']
        regions = ", ".join(account_info['regions'])
        table.add_row(account_id, account_name, regions)
        
    console.print(table)

def display_manual_instructions_workflow(): #TODO: Transform into a class so we can use account_ids as a class variable
    account_ids = []
    aws_account_pattern = r'^\d{12}$'
    sts_client = boto3.client('sts', region_name="us-east-1")    
    ACCOUNT_ID = sts_client.get_caller_identity()["Account"]
    console.print("\n\n[bold yellow]Manual Deployment Instructions:[/bold yellow]")
    console.print("\n1. For each child account you want to collect recommendations for:")
    console.print("   - Log into the AWS child account")
    console.print(f"   - Click this CloudFormation quick create URL: https://us-east-1.console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks/create/review?templateURL=https://bluearch-templates.s3.us-east-1.amazonaws.com/local_cli_version/bluearch_cli_manual_deployment_role.yaml&stackName=bluearch-manual-deployment-role&param_SourceAccount={ACCOUNT_ID}")
    console.print("   - Click Create stack")
    console.print("   - Enter account ID into the terminal")
    console.print("   - Repeat the process for each child account you want to collect recommendations for")
    console.print("\nType 'done' when finished.")
    account_ids = [ACCOUNT_ID]
    
    while True:
        account_id = Prompt.ask("\nEnter one AWS account ID at a time (or [bold green]'done'[/bold green] to proceed)")
        
        if account_id.lower() == 'done':
            if not account_ids:
                console.print("[red]Please enter at least one account ID[/red]")
                continue
            break
        
        if not re.match(aws_account_pattern, account_id):
            console.print("[red]Invalid AWS account ID. It must be exactly 12 digits.[/red]")
            continue
            
        if account_id in account_ids:
            console.print("[yellow]This account ID has already been added.[/yellow]")
            continue
            
        account_ids.append(account_id)
        console.print(f"[green]Account ID {account_id} added successfully![/green]")

    console.print("\n[bold]Collected Account IDs:[/bold]")
    for idx, acc_id in enumerate(account_ids, 1):
        console.print(f"{idx}. {acc_id}")

    proceed = Prompt.ask("\nDo you want to proceed with these accounts?", choices=["yes", "no"], default="no")
    
    if proceed == "yes":
        return account_ids
    else:
        console.print("[yellow]Process cancelled. Please start over.[/yellow]")
        return display_manual_instructions_workflow()

def display_updatable_recommendations(updatables):
    if not updatables:
        console.print("[bold yellow]No updatable recommendations found[/bold yellow]")
        return None

    console.print("[bold yellow]Updatable recommendations:[/bold yellow]")
    table = Table(show_header=True, header_style="bold magenta", show_lines=True)
    table.add_column("Account", style="dim")
    table.add_column("Region", style="dim")
    table.add_column("Recommendation Type", style="dim")
    attribute_keys = set()
    for account, regions in updatables.items():
        for region, rec_types in regions.items():
            for rec_type, recommendations in rec_types.items():
                for recommendation in recommendations:
                    attribute_keys.update(recommendation.keys())
    for key in attribute_keys:
        table.add_column(key, style="dim")
    for account, regions in updatables.items():
        for region, rec_types in regions.items():
            for rec_type, recommendations in rec_types.items():
                for recommendation in recommendations:
                    row = [account, region, rec_type] + [
                        str(recommendation.get(key, "")) for key in attribute_keys
                    ]
                    table.add_row(*row)
    console.print(table)
    console.print()

def display_recommendations(serialized_recommendations):
    rec_type_tables = {}

    for (account, account_name), regions in serialized_recommendations.items():
        for region, rec_types in regions.items():
            for rec_type, recommendations in rec_types.items():
                if rec_type not in rec_type_tables:
                    rec_type_tables[rec_type] = Table(
                        title=f"Recommendations: {rec_type}",
                        show_header=True,
                        header_style="bold magenta",
                        show_lines=True,
                    )
                    rec_type_tables[rec_type].add_column("Account ID", style="dim")
                    rec_type_tables[rec_type].add_column("Account Name", style="dim")
                    rec_type_tables[rec_type].add_column("Region", style="dim")

                attribute_keys = set()
                for recommendation in recommendations:
                    attribute_keys.update(recommendation.keys())

                if len(rec_type_tables[rec_type].columns) == 3:  # Only Account ID, Account Name, and Region columns
                    for key in attribute_keys:
                        rec_type_tables[rec_type].add_column(key, style="dim")

                for recommendation in recommendations:
                    row = [account, account_name, region] + [
                        str(recommendation.get(key, "")) for key in attribute_keys
                    ]
                    rec_type_tables[rec_type].add_row(*row)

    for table in rec_type_tables.values():
        console.print(table)
        console.print()

def display_recommendation_types(recommendation_types):
    table = Table(show_header=True, header_style="bold magenta", show_lines=True)
    table.add_column("Recommendation Type", style="dim")
    for recommendation_type in recommendation_types:
        table.add_row(recommendation_type)
    console.print(table)

def display_stack_resources(resources):
    table = Table(show_header=True, header_style="bold magenta", show_lines=True)
    table.add_column("Logical ID", style="cyan")
    table.add_column("Type", style="blue")
    table.add_column("Status", style="magenta")

    for resource in resources:
        status = resource['ResourceStatus']
        status_style = "green" if status == "CREATE_COMPLETE" else "yellow" if status == "CREATE_IN_PROGRESS" else "red"
        table.add_row(
            resource['LogicalResourceId'],
            resource['ResourceType'],
            f"[{status_style}]{status}[/{status_style}]"
        )

    console.print(table)

def display_scheduler_info():
    title = "Populate Rate Configuration"
    
    instructions = Text("Set the rate time of your populate. The pattern should follow:", style="yellow")
    pattern = Text("(number) (time)", style="green bold")
    
    examples_table = Table(show_header=False, box=None)
    examples_table.add_column(style="cyan")
    examples_table.add_row("1 hour")
    examples_table.add_row("7 days")
    examples_table.add_row("30 minutes")
    examples_table.add_row("365 days")
    
    content = Group(
        instructions,
        pattern,
        Text("\nExamples:", style="yellow"),
        examples_table
    )
    
    main_panel = Panel(
        content,
        title=title,
        border_style="yellow",
        expand=False
    )
    
    console.print(main_panel)
def display_updates(updates):
    if not updates:
        console.print(Panel("BlueArch CLI: [bold yellow]No updates available[/bold yellow]", title="Updates"))
        return

    def _parse_version(v):
        v = str(v or "").lstrip("v").strip()
        parts = []
        for seg in v.split("."):
            try:
                parts.append(int(seg))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    try:
        updates = sorted(updates, key=lambda u: _parse_version(u.get("version", "0")), reverse=True)
    except Exception:
        pass

    latest_version = updates[0].get("version", "?")
    console.print(
        f"\nBlueArch CLI: There's a new version available: [bold cyan]{latest_version}[/bold cyan]\n"
    )

    blocks = []
    for idx, update in enumerate(updates):
        version = update.get("version", "N/A")
        date = (update.get("date") or "").split("T")[0] or "N/A"
        message = (update.get("message", "") or "").strip().replace("[unreleased]", "").strip()

        bracket = f"[{version.lstrip('v')}]"
        if message.startswith(bracket):
            message = message[len(bracket):].lstrip()
        bracket_v = f"[{version}]"
        if message.startswith(bracket_v):
            message = message[len(bracket_v):].lstrip()

        if not message:
            message = "(no changelog)"

        header = Text.assemble(
            (f"v{version.lstrip('v')}", "bold cyan"),
            ("  •  ", "dim"),
            (date, "blue"),
        )
        body = Text(message)

        blocks.append(header)
        blocks.append(Text(""))
        blocks.append(body)
        if idx < len(updates) - 1:
            blocks.append(Text(""))
            blocks.append(Text("─" * 60, style="dim"))
            blocks.append(Text(""))

    console.print(
        Panel(
            Group(*blocks),
            title="Available Updates",
            border_style="cyan",
            padding=(1, 2),
            expand=False,
        )
    )

def display_bluearch_ascii_art():
    from art import text2art
    ascii_art = text2art("BlueArch", font="big",)
    colored_ascii_art = colored(ascii_art, "blue")
    return colored_ascii_art