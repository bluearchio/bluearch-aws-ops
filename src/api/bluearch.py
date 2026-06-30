import os
import sys
from typer import Typer, Option, Context, Exit
from rich.console import Console
from aws.misc.version_controller import CURRENT_VERSION


def _parse_managed_web_start_args(default_host: str, default_port: int) -> dict:
    args = sys.argv[3:]
    values = {
        "host": default_host,
        "port": default_port,
        "daemon": False,
        "log_level": "info",
        "no_browser": False,
    }
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("--daemon", "-d"):
            values["daemon"] = True
        elif arg == "--no-browser":
            values["no_browser"] = True
        elif arg in ("--host", "-H") and index + 1 < len(args):
            index += 1
            values["host"] = args[index]
        elif arg.startswith("--host="):
            values["host"] = arg.split("=", 1)[1]
        elif arg in ("--port", "-p") and index + 1 < len(args):
            index += 1
            values["port"] = int(args[index])
        elif arg.startswith("--port="):
            values["port"] = int(arg.split("=", 1)[1])
        elif arg in ("--log-level", "-l") and index + 1 < len(args):
            index += 1
            values["log_level"] = args[index]
        elif arg.startswith("--log-level="):
            values["log_level"] = arg.split("=", 1)[1]
        index += 1
    return values


def _maybe_run_managed_web_start() -> None:
    if os.environ.get("BLUEARCH_CORE_MANAGED_WEB_START") != "1":
        return
    if sys.argv[1:3] != ["web", "start"]:
        return
    from cli.web import start

    try:
        start(**_parse_managed_web_start_args("127.0.0.1", 8095))
    except Exit as exc:
        raise SystemExit(exc.exit_code) from exc
    raise SystemExit(0)


_maybe_run_managed_web_start()

# Command imports
from cli.version import version_callback
from cli.config import show_accounts_and_regions, update
from cli.recommendations import show_recommendation_types, show_recommendations
from cli.notifications import alarm
from cli.opt_in_central import optin_hub
from cli.scan import scan
from cli.web import web_app
from cli.setup import setup_app
from cli.log_analysis import log_analysis_app

console = Console()
cli_app = Typer(
    help=(
        "[bold]BlueArch CLI[/bold] -- AWS infrastructure recommendations and alerting.\n\n"
        f"Version: [yellow]{CURRENT_VERSION}[/yellow]\n\n"
        "[bold cyan]Core Features:[/bold cyan]\n"
        "  [green]scan[/green]                     Collect AWS resources locally (14 services)\n"
        "  [green]recommendations[/green]          View idle resources, cost savings, security issues\n"
        "  [green]logs[/green]                     Scan CloudWatch Logs for errors + AI root-cause\n"
        "  [green]alarm[/green]                    Configure CloudWatch alarms with SNS/Slack\n"
        "  [green]web[/green]                      Launch browser-based dashboard\n\n"
        "[dim]Run [cyan]bluearch interactive[/cyan] for a guided menu, or [cyan]bluearch -h[/cyan] for full command list[/dim]"
    ),
    rich_markup_mode="rich",
    add_completion=True,
    no_args_is_help=False,
    context_settings=dict(
        help_option_names=["-h", "--help"],
    ),
)


def _show_main_help():
    """Custom help output when invoked with no subcommand."""
    console.print()
    console.print(f"[bold]BlueArch CLI[/bold]  [dim]v{CURRENT_VERSION}[/dim]")
    console.print("[dim]AWS infrastructure recommendations and alerting[/dim]")
    console.print()
    console.print("[bold cyan]Quick Start:[/bold cyan]")
    console.print("  bluearch scan                  Scan AWS resources (no setup needed)")
    console.print("  bluearch recommendations       View findings")
    console.print("  bluearch-core start --daemon   Launch core and web dashboards")
    console.print()
    console.print("[bold cyan]Scan & Analyze:[/bold cyan]")
    console.print("  bluearch scan                  Collect resources locally (14 services)")
    console.print("  bluearch scan -s ec2,rds       Scan specific services")
    console.print("  bluearch scan --skip-scan      Reuse recent data")
    console.print("  bluearch recommendations       List recommendations (filterable)")
    console.print("  bluearch recommendation-types  List recommendation types found")
    console.print()
    console.print("[bold cyan]Alerting:[/bold cyan]")
    console.print("  bluearch alarm                 Configure CloudWatch alarms")
    console.print("  bluearch alarm --config-targets  Manage notification targets (email/Slack)")
    console.print()
    console.print("[bold cyan]Log Analysis:[/bold cyan]")
    console.print("  bluearch logs scan             Scan CloudWatch Logs for error patterns")
    console.print("  bluearch logs errors           View log analysis findings")
    console.print("  bluearch logs analyze ID       AI root-cause analysis on a finding")
    console.print()
    console.print("[bold cyan]Web Dashboard:[/bold cyan]")
    console.print("  bluearch-core start --daemon   Start core and web dashboards")
    console.print("  bluearch web stop              Stop the dashboard")
    console.print()
    console.print("[bold cyan]Setup & Config:[/bold cyan]")
    console.print("  bluearch setup wizard          Guided setup wizard")
    console.print("  bluearch setup assume-role     Configure assume-role authentication")
    console.print("  bluearch setup multi-account   Deploy cross-account StackSet")
    console.print("  bluearch optin-hub             Enable AWS services at org level")
    console.print("  bluearch setup alarms          Manage custom alarms")
    console.print("  bluearch setup validate        Check AWS credentials & permissions")
    console.print("  bluearch setup multi-account --status  Show StackSet deployment status")
    console.print()
    console.print("[dim]Run [cyan]bluearch -h[/cyan] for full command list, or [cyan]bluearch interactive[/cyan] for a guided menu[/dim]")
    console.print()


def _ensure_core_for_command(ctx: Context) -> None:
    """Require a compatible core runtime for product commands.

    `bluearch update` is intentionally exempt so users can repair or install
    the required core runtime through the product updater.
    """
    if ctx.invoked_subcommand in (None, "update", "web"):
        return
    if any(arg in sys.argv for arg in ("--help", "-h", "--version", "--install-completion", "--show-completion")):
        return
    try:
        from utils.core_client import MINIMUM_CORE_VERSION, check_core_dependency

        check_core_dependency("bluearch")
    except Exception as exc:
        console.print("[red]bluearch-core is required before using BlueArch CLI commands.[/red]")
        console.print(f"[dim]{exc}[/dim]")
        console.print(f"[cyan]Required version:[/cyan] bluearch-core >= {MINIMUM_CORE_VERSION}")
        console.print("[cyan]Install or update it with:[/cyan] bluearch update")
        console.print("[cyan]Start it with:[/cyan] bluearch-core start --daemon")
        raise Exit(1)


@cli_app.callback(invoke_without_command=True)
def main(
    ctx: Context,
    version: bool = Option(
        None,
        "--version",
        callback=version_callback,
        help="Print the current version and check for updates",
    ),
    show_help: bool = Option(
        False,
        "--help-full",
        help="Show full command reference",
    ),
):
    """[bold]BlueArch CLI[/bold] -- AWS infrastructure recommendations and alerting.

    [dim]Runs locally -- no CloudFormation deployment required. Just configure AWS credentials and scan.[/dim]
    """
    # Non-blocking update notice (reads local cache only, never blocks)
    try:
        from utils.version_check import check_for_update_notice
        check_for_update_notice()
    except Exception:
        pass

    _ensure_core_for_command(ctx)

    if ctx.invoked_subcommand is None:
        try:
            from utils.onboarding import is_first_time_user, run_onboarding
            if is_first_time_user():
                run_onboarding()
                return
        except Exception:
            pass

        # Default: show help. Users who want the interactive menu can run
        # `bluearch interactive` explicitly.
        _show_main_help()


def register_commands():
    # Scan & Analyze — primary names
    cli_app.command(name="scan", rich_help_panel="Scan & Analyze")(scan)
    cli_app.command(name="recommendations", rich_help_panel="Scan & Analyze")(show_recommendations)
    cli_app.command(name="recommendation-types", rich_help_panel="Scan & Analyze")(show_recommendation_types)

    # Scan & Analyze — hidden aliases (preserve backward compatibility)
    cli_app.command(name="show-recommendations", hidden=True)(show_recommendations)
    cli_app.command(name="show-recommendation-types", hidden=True)(show_recommendation_types)

    # Alerting
    cli_app.command(name="alarm", rich_help_panel="Alerting")(alarm)
    cli_app.command(name="optin-hub", rich_help_panel="Setup & Config")(optin_hub)

    # Setup & Config
    cli_app.add_typer(setup_app, name="setup", rich_help_panel="Setup & Config")
    cli_app.command(name="update", rich_help_panel="Setup & Config")(update)
    cli_app.command(name="discovered-accounts", rich_help_panel="Setup & Config")(show_accounts_and_regions)

    # Setup & Config — hidden aliases (preserve backward compatibility)
    cli_app.command(name="show-accounts-and-regions", hidden=True)(show_accounts_and_regions)

    # Log analysis
    cli_app.add_typer(log_analysis_app, name="logs", rich_help_panel="Log Analysis")

    # Web dashboard
    cli_app.add_typer(web_app, name="web", rich_help_panel="Web Dashboard")

    # Interactive menu (also accessible explicitly)
    def interactive():
        """Launch interactive guided menu.

        [green]Example:[/green]
          bluearch interactive
        """
        from cli.interactive import run_interactive_menu
        run_interactive_menu()

    cli_app.command(name="interactive", rich_help_panel="General")(interactive)
    cli_app.command(name="menu", hidden=True)(interactive)


register_commands()


def run():
    try:
        cli_app()
    except (SystemExit, KeyboardInterrupt):
        raise
    except ValueError as e:
        print(e)


if __name__ == "__main__":
    run()
