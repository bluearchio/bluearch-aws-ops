"""Multi-account cross-account scanning commands."""

from datetime import datetime, timezone
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from utils.core_client import request_core

accounts_app = typer.Typer(
    help="Manage cross-account role configurations for multi-account scanning",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()

STACKSET_NAME = "BlueArchCLI-CrossAccount-Infrastructure"
CROSS_ACCOUNT_ROLE_NAME = "BlueArchRole"


@accounts_app.command(name="add")
def accounts_add(
    account_id: str = typer.Option(..., "--account-id", "-a", prompt="AWS Account ID", help="12-digit AWS account ID"),
    role_name: str = typer.Option("BlueArchCLIRole", "--role-name", "-r", prompt="IAM Role Name", help="IAM role name to assume"),
    external_id: Optional[str] = typer.Option(None, "--external-id", "-e", help="External ID for role assumption"),
    alias: Optional[str] = typer.Option(None, "--alias", help="Friendly alias for this account"),
):
    """
    Add an AWS account for cross-account scanning.

    [green]Examples:[/green]
      bluearch-aws-ops accounts add -a 123456789012 -r BlueArchCLIRole
      bluearch-aws-ops accounts add -a 123456789012 -r BlueArchCLIRole -e my-external-id --alias production
    """
    # Validate account ID format
    if not account_id.isdigit() or len(account_id) != 12:
        console.print("[red]Account ID must be a 12-digit number.[/red]")
        raise typer.Exit(1)

    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"

    existing = _find_assume_role_config(account_id)
    if existing:
        console.print(f"[yellow]Account {account_id} is already configured (role: {existing.get('role_arn')}).[/yellow]")
        console.print("[dim]Use 'bluearch-aws-ops accounts remove' first to reconfigure.[/dim]")
        raise typer.Exit(0)

    _create_assume_role_config(
        {
            "account_id": account_id,
            "role_arn": role_arn,
            "role_name": role_name,
            "external_id": external_id,
            "alias": alias,
            "enabled": True,
        }
    )

    console.print()
    console.print(f"[green]Account added successfully[/green]")
    console.print(f"  Account ID:  [cyan]{account_id}[/cyan]")
    console.print(f"  Role ARN:    [cyan]{role_arn}[/cyan]")
    if external_id:
        console.print(f"  External ID: [cyan]{external_id}[/cyan]")
    if alias:
        console.print(f"  Alias:       [cyan]{alias}[/cyan]")
    console.print()
    console.print("[dim]Run [cyan]bluearch-aws-ops accounts test -a {0}[/cyan] to verify role assumption.[/dim]".format(account_id))


@accounts_app.command(name="list")
def accounts_list():
    """List all configured cross-account roles."""
    configs = _list_assume_role_configs()

    if not configs:
        console.print("[dim]No cross-account roles configured.[/dim]")
        console.print("[dim]Use [cyan]bluearch-aws-ops accounts add[/cyan] to add one.[/dim]")
        return

    table = Table(
        title="Cross-Account Configurations",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Account ID")
    table.add_column("Alias")
    table.add_column("Role Name")
    table.add_column("External ID")
    table.add_column("Enabled")
    table.add_column("Last Used")

    for config in configs:
        external_id = config.get("external_id")
        table.add_row(
            config.get("account_id") or "-",
            config.get("alias") or "-",
            config.get("role_name") or "-",
            external_id[:12] + "..." if external_id and len(external_id) > 12 else (external_id or "-"),
            "[green]Yes[/green]" if config.get("enabled") else "[dim]No[/dim]",
            _format_time(config.get("last_used_at")),
        )

    console.print(table)


@accounts_app.command(name="remove")
def accounts_remove(
    account_id: str = typer.Option(..., "--account-id", "-a", prompt="AWS Account ID to remove", help="12-digit AWS account ID"),
):
    """
    Remove a cross-account configuration.

    [green]Examples:[/green]
      bluearch-aws-ops accounts remove -a 123456789012
    """
    config = _find_assume_role_config(account_id)

    if not config:
        console.print(f"[yellow]No configuration found for account {account_id}.[/yellow]")
        raise typer.Exit(0)

    alias_str = f" ({config.get('alias')})" if config.get("alias") else ""
    _delete_assume_role_config(config["id"])

    console.print(f"[green]Removed account {account_id}{alias_str}[/green]")


@accounts_app.command(name="test")
def accounts_test(
    account_id: str = typer.Option(..., "--account-id", "-a", prompt="AWS Account ID to test", help="12-digit AWS account ID"),
):
    """
    Test role assumption for a configured account.

    [green]Examples:[/green]
      bluearch-aws-ops accounts test -a 123456789012
    """
    config = _find_assume_role_config(account_id)

    if not config:
        console.print(f"[yellow]No configuration found for account {account_id}.[/yellow]")
        console.print("[dim]Use [cyan]bluearch-aws-ops accounts add[/cyan] to configure it first.[/dim]")
        raise typer.Exit(1)

    role_arn = config["role_arn"]
    console.print(f"Testing role assumption for account [cyan]{account_id}[/cyan]...")
    console.print(f"  Role ARN: {role_arn}")

    try:
        result = request_core(
            "POST",
            f"/api/v1/assume-role/test/{config['id']}",
            service_token=True,
            timeout=20.0,
        )
    except Exception as exc:
        console.print()
        console.print(f"[red]Role assumption failed[/red]")
        console.print(f"  Error: {exc}")
        raise typer.Exit(1)

    if result.get("success"):
        console.print()
        console.print("[green]Role assumption successful[/green]")
        console.print(f"  Assumed Role ARN: [cyan]{result.get('assumed_identity') or '-'}[/cyan]")
        console.print(f"  Account:          [cyan]{result.get('account_id') or account_id}[/cyan]")
        return

    console.print()
    console.print(f"[red]Role assumption failed[/red]")
    console.print(f"  Error: {result.get('error') or 'Unknown error'}")
    console.print()
    console.print("[dim]Check that:[/dim]")
    console.print("[dim]  1. The role exists in the target account[/dim]")
    console.print("[dim]  2. The trust policy allows your current account/role[/dim]")
    console.print("[dim]  3. The external ID matches (if configured)[/dim]")
    raise typer.Exit(1)


def _list_assume_role_configs() -> List[dict]:
    return request_core("GET", "/api/v1/assume-role/configs", timeout=10.0) or []


def _find_assume_role_config(account_id: str) -> Optional[dict]:
    return next((config for config in _list_assume_role_configs() if config.get("account_id") == account_id), None)


def _create_assume_role_config(payload: dict) -> dict:
    return request_core(
        "POST",
        "/api/v1/assume-role/add",
        service_token=True,
        json=payload,
        timeout=10.0,
    )


def _delete_assume_role_config(record_id: str) -> None:
    request_core(
        "DELETE",
        f"/api/v1/assume-role/{record_id}",
        service_token=True,
        timeout=10.0,
    )


def _format_time(value) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return "-"
    else:
        return "-"
    return parsed.strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# StackSet deployment commands (owned by bluearch-core)
# ---------------------------------------------------------------------------


def _submit_core_setup_job(
    path: str,
    *,
    payload: dict | None = None,
    action: str,
    timeout_seconds: int = 900,
) -> dict:
    job = request_core(
        "POST",
        path,
        service_token=True,
        json=payload or {},
        timeout=20.0,
    )
    job_id = job.get("job_id") or job.get("id")
    if not job_id:
        raise RuntimeError(f"bluearch-core did not return a job id for {action}")
    console.print(f"[cyan]{action} started in bluearch-core (job {job_id})[/cyan]")
    return _wait_for_core_setup_job(str(job_id), action, timeout_seconds=timeout_seconds)


def _wait_for_core_setup_job(job_id: str, action: str, *, timeout_seconds: int = 900) -> dict:
    start = datetime.now(timezone.utc)
    last_message = None
    last_progress = None
    while (datetime.now(timezone.utc) - start).total_seconds() < timeout_seconds:
        job = request_core("GET", f"/api/v1/jobs/{job_id}", timeout=10.0)
        progress = job.get("progress")
        message = job.get("progress_message") or job.get("message") or job.get("status")
        if message != last_message or progress != last_progress:
            if progress is not None:
                console.print(f"[dim]{int(progress):>3}% {message}[/dim]")
            else:
                console.print(f"[dim]{message}[/dim]")
            last_message = message
            last_progress = progress
        if job.get("status") == "completed":
            return job.get("result") or {}
        if job.get("status") == "failed":
            raise RuntimeError(job.get("error") or message or f"{action} failed")
        import time

        time.sleep(3)
    raise RuntimeError(f"Timed out waiting for bluearch-core job {job_id}")


def _parse_csv_option(value: Optional[str]) -> list[str] | None:
    if not value:
        return None
    parsed = [item.strip() for item in value.split(",") if item.strip()]
    return parsed or None


def _print_core_stackset_status(status_payload: dict) -> None:
    if not status_payload.get("exists"):
        console.print(f"[yellow]No StackSet deployed. Run [cyan]bluearch-aws-ops accounts deploy[/cyan] to create it.[/yellow]")
        return

    console.print(f"  StackSet: [cyan]{status_payload.get('stackset_name') or STACKSET_NAME}[/cyan]")
    console.print(f"  Status:   [green]{status_payload.get('status', 'UNKNOWN')}[/green]")
    if status_payload.get("template_version"):
        console.print(f"  Version:  [cyan]{status_payload.get('template_version')}[/cyan]")

    instances = status_payload.get("instances") or []
    if not instances:
        console.print("[yellow]No stack instances deployed.[/yellow]")
        return

    table = Table(title=f"Stack Instances ({len(instances)})", show_header=True, header_style="bold cyan")
    table.add_column("Account ID")
    table.add_column("Region")
    table.add_column("Status")
    table.add_column("Reason", overflow="fold")
    for instance in instances:
        status = instance.get("status") or "UNKNOWN"
        color = "green" if status == "CURRENT" else ("yellow" if status == "OUTDATED" else "red")
        table.add_row(
            instance.get("account_id") or "-",
            instance.get("region") or "-",
            f"[{color}]{status}[/{color}]",
            instance.get("status_reason") or "-",
        )
    console.print(table)


@accounts_app.command(name="status")
def accounts_status():
    """Show the current cross-account StackSet status and instances."""
    try:
        status_payload = request_core("GET", "/api/v1/accounts/status", timeout=15.0)
    except Exception as exc:
        console.print(f"[red]bluearch-core account status unavailable: {exc}[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]Checking StackSet [b]{STACKSET_NAME}[/b] through bluearch-core...[/cyan]")
    _print_core_stackset_status(status_payload)


@accounts_app.command(name="deploy")
def accounts_deploy(
    accounts: Optional[str] = typer.Option(
        None,
        "--accounts",
        "-a",
        help="Comma-separated account IDs. Defaults to the organization root.",
    ),
    organizational_units: Optional[str] = typer.Option(
        None,
        "--ous",
        help="Comma-separated OU IDs. Defaults to the organization root.",
    ),
    regions: Optional[str] = typer.Option(
        None,
        "--regions",
        "-R",
        help="Comma-separated regions to deploy to.",
    ),
    force_recreate: bool = typer.Option(
        False,
        "--force-recreate",
        help="Delete and recreate the StackSet through bluearch-core.",
    ),
):
    """Deploy the cross-account StackSet through bluearch-core."""
    try:
        validation = request_core("GET", "/api/v1/accounts/validate", timeout=15.0)
    except Exception as exc:
        console.print(f"[red]bluearch-core account validation unavailable: {exc}[/red]")
        raise typer.Exit(1)

    if not validation.get("can_deploy"):
        guidance = validation.get("guidance") or validation.get("error") or (
            "Run from the management account or a delegated CloudFormation StackSets admin."
        )
        console.print(f"[red]Prerequisites check failed: {guidance}[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]Deploying [b]{STACKSET_NAME}[/b] through bluearch-core[/cyan]")
    try:
        result = _submit_core_setup_job(
            "/api/v1/accounts/deploy",
            payload={
                "accounts": _parse_csv_option(accounts),
                "organizational_units": _parse_csv_option(organizational_units),
                "regions": _parse_csv_option(regions),
                "force_recreate": force_recreate,
            },
            action="Cross-account deployment",
            timeout_seconds=1800,
        )
    except Exception as exc:
        console.print(f"[red]Deployment failed through bluearch-core: {exc}[/red]")
        raise typer.Exit(1)

    deployed_accounts = result.get("deployed_accounts") or []
    failed_accounts = result.get("failed_accounts") or []
    synced_accounts = result.get("synced_accounts")
    console.print()
    console.print("[green]StackSet deployment complete.[/green]")
    console.print(f"  Deployed accounts: [green]{len(deployed_accounts)}[/green]")
    if failed_accounts:
        console.print(f"  Failed accounts:   [red]{len(failed_accounts)}[/red]")
    if synced_accounts is not None:
        console.print(f"  Synced targets:    [cyan]{synced_accounts}[/cyan]")


@accounts_app.command(name="update")
def accounts_update():
    """Update the existing StackSet to the latest core-owned template."""
    console.print(f"[cyan]Updating [b]{STACKSET_NAME}[/b] template through bluearch-core...[/cyan]")
    try:
        _submit_core_setup_job(
            "/api/v1/accounts/update",
            action="Cross-account update",
            timeout_seconds=1800,
        )
    except Exception as exc:
        console.print(f"[red]Update failed through bluearch-core: {exc}[/red]")
        raise typer.Exit(1)
    console.print("[green]Update complete.[/green]")


@accounts_app.command(name="delete-stackset")
def accounts_delete_stackset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
):
    """Delete all stack instances and the cross-account StackSet through bluearch-core."""
    if not yes:
        confirm = typer.confirm(
            f"This will delete the StackSet '{STACKSET_NAME}' and all member-account stacks. Continue?"
        )
        if not confirm:
            raise typer.Abort()

    try:
        result = _submit_core_setup_job(
            "/api/v1/accounts/remove",
            action="Cross-account removal",
            timeout_seconds=1800,
        )
    except Exception as exc:
        console.print(f"[red]Removal failed through bluearch-core: {exc}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]{result.get('message') or 'StackSet deleted.'}[/green]")
