from typer import Option
from collections import Counter
import json


def _list_recommendations(account_id=None, region=None, recommendation_type=None) -> list[dict]:
    from utils.core_client import request_core

    params = [("limit", 10000), ("order_by", "recommendation_type"), ("descending", "false")]
    if account_id:
        params.append(("filter", f"account_id={account_id}"))
    if region:
        params.append(("filter", f"region_name={region}"))
    if recommendation_type:
        params.append(("filter", f"recommendation_type={recommendation_type}"))
    rows = request_core(
        "GET",
        "/api/v1/storage/bluearch/recommendations",
        service_token=True,
        params=params,
        timeout=10.0,
    )
    return [row.get("payload", row) for row in rows or []]

def show_recommendations(
    account_id: str = Option(None, "--account-id", "-a", help="The account ID to filter recommendations by."),
    region: str = Option(None, "--region", "-r", help="The region to filter recommendations by."),
    recommendation_type: str = Option(None, "--recommendation-type", "-t", help="The type of recommendation to filter by.")
):
    """
    Retrieves recommendations from bluearch-core.

    [yellow]You can filter the recommendations by:[/yellow]
    [green]- Account ID[/green]
    [green]- Region[/green]
    [green]- Recommendation Type[/green]

    [yellow]Example:[/yellow]
    [green]bluearch show-recommendations --account-id 123456789012 -r us-east-1 -t unattached_ec2_volumes[/green]
    """
    from rich.console import Console
    from rich.table import Table

    console = Console()
    recs = _list_recommendations(account_id=account_id, region=region, recommendation_type=recommendation_type)
    if not recs:
        console.print("[yellow]No recommendations found. Run [cyan]bluearch scan[/cyan] first.[/yellow]")
        return

    table = Table(title=f"Recommendations ({len(recs)})", show_header=True, header_style="bold cyan")
    table.add_column("Type")
    table.add_column("Resource")
    table.add_column("Account")
    table.add_column("Region")
    table.add_column("Rationale")

    for rec in recs:
        attrs = rec.get("attributes")
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except (json.JSONDecodeError, TypeError):
                attrs = {}
        attrs = attrs or {}
        table.add_row(
            str(rec.get("recommendation_type") or "").replace("_", " "),
            str(attrs.get("resource_id") or rec.get("resource_id") or "-"),
            rec.get("account_name") or rec.get("account_id") or "-",
            rec.get("region_name") or "-",
            str(attrs.get("ActionRationale", "-")),
        )

    console.print(table)


def show_recommendation_types():
    """
    Displays the collected recommendation types.
    """
    from rich.console import Console
    from rich.table import Table

    console = Console()
    recs = _list_recommendations()
    types = Counter(rec.get("recommendation_type") or "unknown" for rec in recs)

    if not types:
        console.print("[yellow]No recommendation types found. Run [cyan]bluearch scan[/cyan] first.[/yellow]")
        return

    table = Table(title="Recommendation Types", show_header=True, header_style="bold cyan")
    table.add_column("Type")
    table.add_column("Count", justify="right")

    for rec_type, count in types.most_common():
        table.add_row(rec_type.replace("_", " "), str(count))

    console.print(table)

def scheduler(
    get: bool = Option(False, "--get", "-g", help="Get the current scheduler frequency."),
    disable: bool = Option(False, "--disable", "-d", help="Disable the scheduler.")
):
    """
    Automate the process of populating recommendations and generating reports.


    [yellow]Example:[/yellow]
    [green]bluearch scheduler -g[/green]
    [green]bluearch scheduler -d[/green]

    More information:
    [blue]https://docs.bluearch.io/bluearch-cli#/?id=scheduler[/blue]
    """
    from aws.misc.error_handlings import error_handler
    from aws.wrappers.eventbridge import EventBridge
    from aws.wrappers.sfn import StateMachine
    from aws.misc import display
    from rich.console import Console
    from rich.prompt import Prompt

    console = Console()
    def execute_scheduler():
        try:
            eb_client = EventBridge()
            if get:
                if eb_client.GetScheduleStatus() == "DISABLED":
                    console.print("[yellow]The scheduler is currently disabled. Run 'bluearch scheduler' to enable it.[/yellow]")
                    return
                
                scheduler_expression = eb_client.GetScheduleExpression()
                console.print(f"[blue]Current scheduler rate: {scheduler_expression}[/blue]")
                return
            
            if disable:
                if eb_client.GetScheduleStatus() == "DISABLED":
                    console.print("[yellow]The scheduler is already disabled. Run 'bluearch scheduler' to enable it.[/yellow]")
                    return

                if Prompt.ask("[blue]Do you want to disable the populate scheduler?[/blue]", choices=["yes", "no"], default="no") == "yes":
                    eb_client.SetScheduleExpression()
                    console.print("[yellow]Scheduler disabled successfully.[/yellow]")
                    return
            
            sfn_client = StateMachine()
            check_previous_execution = sfn_client.check_previous_execution()
            if check_previous_execution is None:
                if Prompt.ask("[blue]No previous populate execution found. Do you want to populate now?[/blue]", choices=["yes", "no"], default="no") == "yes":
                    populate()
                else:
                    return

            display.display_scheduler_info()
            while True:
                schedule_expression = Prompt.ask("[blue]Enter the desired rate time of your scheduler[/blue]")
                is_valid, validated_expression = eb_client.ValidateScheduleExpression(schedule_expression)
                if is_valid:
                    result = eb_client.SetScheduleExpression(validated_expression, "ENABLED")
                    console.print(f"[green]Scheduler enabled successfully. Set to run every: {result}.[/green]")
                    break
                else:
                    console.print("[red]Invalid schedule expression. Please try again.[/red]")
        except Exception as e:
            error_handler.handle_error(e)

    execute_scheduler()

def populate():
    """
    Run the State Machine execution to populate the recommendations. 
    
    [yellow]The command does not update any resource, it is a read only operation that saves the information into the AWS S3 and DynamoDB Table.[/yellow]
    """
    from aws.misc.error_handlings import error_handler
    from aws.wrappers.co import ComputeOptimizer
    from aws.wrappers.organizations import Organizations
    from aws.wrappers.eventbridge import EventBridge
    from commons import get
    from commons.execution import populate as execute_populate
    from rich.console import Console
    from rich.prompt import Prompt
    from cli.recommendations import scheduler

    def execute():
        console = Console()
        try:
            if Prompt.ask("[blue]This operation will not update any AWS resources, it is a Read Only process which saves the information into the AWS S3. \nDo you want to proceed with the population?[/blue]", choices=["yes", "no"], default="no") == "yes":
                # co = ComputeOptimizer()
                # org = Organizations()
                console.print("[blue]Refreshing accounts and regions table...[/blue]")
                get.refresh_accounts_n_regions_table()
                console.print("[green]Accounts and regions table refreshed successfully.[/green]")
                # co.handle_compute_optimizer_activation(org)
                try:
                    execute_populate()
                except Exception as e:
                    error_handler.handle_error(e)
                    return
                eb_client = EventBridge()
                if eb_client.GetScheduleStatus() != "DISABLED":
                    return
                if Prompt.ask("[blue]Do you want to enable the scheduler to run the population automatically?[/blue]", choices=["yes", "no"], default="no") == "yes":
                    scheduler(get=False, disable=False)
            else:
                console.print("Population aborted.")
        except Exception as e:
            error_handler.handle_error(e)

    execute()
