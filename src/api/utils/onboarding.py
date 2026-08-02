"""First-run onboarding wizard — guides new users through setup.

No CloudFormation deployment required. Everything runs locally.
"""

import os
import configparser

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

from utils.config import get_bluearch_home
from utils.core_client import request_core
from utils.display_utils import print_success, print_warning, print_info, print_error

console = Console()


def _onboarded_marker_path() -> str:
    return os.path.join(get_bluearch_home(), ".onboarded")


def _mark_onboarded() -> None:
    """Persist a marker so the wizard doesn't re-run after a completed setup."""
    try:
        path = _onboarded_marker_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("1")
    except Exception:
        pass


def is_first_time_user() -> bool:
    """Check if this is the first time running the CLI."""
    if os.path.exists(_onboarded_marker_path()):
        return False
    try:
        resource_summary = request_core("GET", "/api/v1/resources/summary", timeout=5.0)
        accounts = request_core("GET", "/api/v1/accounts", timeout=5.0)
        has_resources = int(resource_summary.get("total") or 0) > 0
        has_accounts = bool(accounts)
        return not has_resources and not has_accounts
    except Exception:
        return True


def run_onboarding():
    """Interactive onboarding flow for new users."""
    console.print()
    console.print(Panel(
        "[bold cyan]Welcome to BlueArch CLI![/bold cyan]\n\n"
        "BlueArch scans your AWS infrastructure to find recommendations\n"
        "and optimization opportunities.\n\n"
        "[dim]Everything runs locally -- no cloud deployment required.[/dim]",
        border_style="cyan",
    ))
    console.print()

    try:
        ready = Confirm.ask("Ready to get started?", default=True)
    except EOFError:
        # Non-interactive (CI) context
        return
    if not ready:
        return

    # Step 1: AWS Profile
    console.print()
    console.print("[bold]Step 1: AWS Configuration[/bold]")
    console.print()

    profiles = _discover_aws_profiles()
    if profiles:
        _show_profiles_table(profiles)
        console.print()
        print_info("Set your profile with: [bold]export AWS_PROFILE=your-profile[/bold]")
        current = os.environ.get("AWS_PROFILE")
        if current:
            print_success(f"Current profile: {current}")
        else:
            print_warning("No AWS_PROFILE set. Using default credentials.")
    else:
        print_warning("No AWS profiles found in ~/.aws/config")
        print_info("Configure with: [bold]aws configure[/bold] or [bold]aws sso configure[/bold]")

    # Step 2: Check credentials
    console.print()
    console.print("[bold]Step 2: Verify AWS Access[/bold]")
    console.print()

    account_info = _check_aws_credentials()
    if account_info:
        print_success(f"Connected to AWS account: {account_info['account_id']}")
    else:
        print_error("Could not connect to AWS. Check your credentials.")
        print_info("Run: [bold]aws sso login[/bold]")
        return

    # Step 3: Initialize DB
    console.print()
    console.print("[bold]Step 3: Initialize Database[/bold]")
    console.print()

    try:
        result = request_core(
            "POST",
            "/api/v1/core/db/migrate",
            params=[("import_legacy", "true")],
            timeout=60.0,
        )
        db_path = result.get("db_path") or "bluearch-core"
        print_success(f"Database initialized at {db_path}")
    except Exception as e:
        print_error(f"Database initialization failed: {e}")
        return

    # Step 4: Next steps
    console.print()
    console.print(Panel(
        "[bold]You're all set! Here's what to do next:[/bold]\n\n"
        "  [cyan]bluearch-aws-ops scan[/cyan]                  Scan your AWS resources\n"
        "  [cyan]bluearch-aws-ops recommendations[/cyan]       View findings\n"
        "  [cyan]bluearch-aws-core start --daemon[/cyan]       Launch core and web dashboards",
        title="Next Steps",
        border_style="green",
    ))
    console.print()

    console.print("[dim]The public build does not send hosted usage analytics.[/dim]")
    console.print("[dim]Runtime data stays local unless you configure your own AWS integrations.[/dim]")
    console.print()
    console.print("[dim]The web dashboard is served by the local bluearch-aws-core runtime and protected[/dim]")
    console.print("[dim]with the local service token.[/dim]")
    console.print()

    _mark_onboarded()


def _discover_aws_profiles():
    """Read AWS profiles from ~/.aws/config."""
    config_path = os.path.expanduser("~/.aws/config")
    if not os.path.exists(config_path):
        return []

    config = configparser.ConfigParser()
    config.read(config_path)

    profiles = []
    for section in config.sections():
        name = section.replace("profile ", "")
        region = config.get(section, "region", fallback="")
        sso = "Yes" if config.has_option(section, "sso_start_url") else ""
        profiles.append({"name": name, "region": region, "sso": sso})

    return profiles


def _show_profiles_table(profiles):
    """Display AWS profiles in a Rich table."""
    table = Table(title="AWS Profiles", show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Profile")
    table.add_column("Region")
    table.add_column("SSO")

    for i, p in enumerate(profiles, 1):
        table.add_row(str(i), p["name"], p["region"], p["sso"])

    console.print(table)


def _check_aws_credentials():
    """Verify AWS credentials through bluearch-aws-core. Returns account info or None."""
    try:
        validation = request_core("GET", "/api/v1/setup/validate", timeout=15.0)
        checks = validation.get("checks") if isinstance(validation, dict) else {}
        identity = {}
        if isinstance(checks, dict):
            identity = (checks.get("aws_credentials") or {}).get("identity") or {}
        elif isinstance(checks, list):
            for item in checks:
                if not isinstance(item, dict):
                    continue
                if str(item.get("name", "")).lower().replace(" ", "_") == "aws_credentials":
                    identity = (item.get("details") or {}).get("identity") or {}
                    break
        account_id = identity.get("Account") or identity.get("account_id")
        arn = identity.get("Arn") or identity.get("arn")
        if account_id:
            return {"account_id": account_id, "arn": arn}
    except Exception:
        pass
    return None
