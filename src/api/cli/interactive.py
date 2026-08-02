"""Interactive menu mode - launched when no subcommand is given."""

from rich.console import Console
from rich.prompt import Prompt

console = Console()

MENU_ITEMS = {
    "1": ("Scan", "Run AWS resource scan", "scan"),
    "2": ("View Recommendations", "List findings from last scan", "recommendations"),
    "4": ("Alarms", "Configure CloudWatch alarms", "alarm"),
    "5": ("Setup", "Guided setup wizard", "setup"),
    "6": ("Web Dashboard", "Show the Core-managed start command", "web-help"),
    "0": ("Exit", "", "exit"),
}


def run_interactive_menu():
    """Display the interactive menu and dispatch selected action."""
    from aws.misc.version_controller import CURRENT_VERSION

    console.print()
    console.print(f"[bold]BlueArch CLI[/bold]  [dim]v{CURRENT_VERSION}[/dim]")
    console.print("[dim]AWS infrastructure recommendations and alerting[/dim]")
    console.print()

    for key, (label, description, _) in MENU_ITEMS.items():
        if key == "0":
            console.print(f"  [dim]{key}[/dim]  [dim]{label}[/dim]")
        else:
            console.print(f"  [bold cyan]{key}[/bold cyan]  {label:<25} [dim]{description}[/dim]")

    console.print()

    try:
        choice = Prompt.ask("Select an option", choices=list(MENU_ITEMS.keys()), default="1")
    except (EOFError, KeyboardInterrupt):
        return

    _, _, action = MENU_ITEMS[choice]

    if action == "exit":
        return

    console.print()
    _dispatch(action)


def _dispatch(action: str):
    """Lazy-import and execute the selected action."""
    if action == "scan":
        from cli.scan import scan
        scan(services=None, regions=None, skip_scan=False, skip_scan_age=5, force=False)

    elif action == "recommendations":
        from cli.recommendations import show_recommendations
        show_recommendations(account_id=None, region=None, recommendation_type=None)

    elif action == "alarm":
        from cli.notifications import alarm
        alarm(config_targets=False)

    elif action == "setup":
        from utils.onboarding import run_onboarding
        run_onboarding()

    elif action == "web-help":
        console.print("[cyan]Start the dashboards with:[/cyan] bluearch-aws-core start --daemon")
        console.print("[cyan]Then open:[/cyan] http://localhost:8095")
