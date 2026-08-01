"""Setup commands — wizard, validate, aws-profile (matching tag-manager pattern)."""

import os
import time
from datetime import datetime, timezone
from typing import Any, List, Optional
from urllib.parse import urlencode

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from utils.core_client import CoreRuntimeError, request_core

setup_app = typer.Typer(
    help=(
        "[bold]Setup & Configuration[/bold] -- validate credentials, manage profiles, inspect database.\n\n"
        "[green]Examples:[/green]\n"
        "  bluearch-aws-ops setup wizard       Guided first-time setup\n"
        "  bluearch-aws-ops setup validate     Check AWS credentials and IAM permissions\n"
        "  bluearch-aws-ops setup aws-profile  Select AWS profile interactively\n"
        "  bluearch-aws-ops setup database     Show database status\n"
    ),
    no_args_is_help=False,
    rich_markup_mode="rich",
)

console = Console()


@setup_app.callback(invoke_without_command=True)
def setup_help(ctx: typer.Context):
    """Setup and configuration for BlueArch CLI."""
    if ctx.invoked_subcommand is None:
        console.print()
        console.print("[bold]Setup & Configuration Commands[/bold] - Get started quickly")
        console.print()
        console.print("[bold cyan]INTERACTIVE SETUP (recommended for new users):[/bold cyan]")
        console.print("  wizard         Complete guided setup wizard")
        console.print("  validate       Verify your setup is working correctly")
        console.print()
        console.print("[bold cyan]INDIVIDUAL COMPONENTS (configure separately):[/bold cyan]")
        console.print("  aws-profile    Configure AWS profile and credentials")
        console.print("  database       Initialize database and migrations")
        console.print("  assume-role    Configure assume-role authentication")
        console.print("  multi-account  Deploy cross-account StackSet for multi-account access")
        console.print("  optin-hub      Enable AWS services at the organization level")
        console.print("  alarms         Manage custom alarms for recommendations")
        console.print()
        console.print("[bold cyan]TYPICAL WORKFLOW:[/bold cyan]")
        console.print("  1. bluearch-aws-ops setup wizard      # Complete interactive setup")
        console.print("  2. bluearch-aws-ops setup validate    # Verify everything works")
        console.print("  3. bluearch-aws-ops scan              # Scan AWS resources")
        console.print("  4. bluearch-aws-ops recommendations   # View findings")
        console.print()
        console.print("[bold cyan]MULTI-ACCOUNT SETUP (AWS Organizations):[/bold cyan]")
        console.print("  bluearch-aws-ops setup assume-role --deploy      # Deploy IAM role via CloudFormation")
        console.print("  bluearch-aws-ops setup multi-account --complete  # Deploy cross-account infrastructure")
        console.print()


@setup_app.command()
def wizard():
    """Run the guided setup wizard."""
    from utils.onboarding import run_onboarding
    run_onboarding()


@setup_app.command()
def validate():
    """Check setup status through bluearch-aws-core."""
    console.print()
    console.print("[bold]Validating AWS Configuration[/bold]")
    console.print()

    try:
        result = _normalize_core_setup_validation(
            request_core("GET", "/api/v1/setup/validate", timeout=15.0)
        )
    except Exception as exc:
        console.print(f"  [red]>> bluearch-aws-core setup validation unavailable: {exc}[/red]")
        raise typer.Exit(1)

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Message", overflow="fold")
    for check in result["checks"]:
        status = check.get("status") or "unknown"
        table.add_row(
            check.get("name") or "-",
            f"[{_status_color(status)}]{status}[/{_status_color(status)}]",
            check.get("message") or "-",
        )
    console.print(table)

    console.print()
    if result["overall"] in {"healthy", "ok"}:
        console.print("[green]Setup validation passed through bluearch-aws-core[/green]")
    else:
        console.print(f"[yellow]Setup status: {result['overall']}[/yellow]")
        raise typer.Exit(1)
    console.print()


def _normalize_core_setup_validation(payload: dict[str, Any]) -> dict[str, Any]:
    checks = payload.get("checks") if isinstance(payload, dict) else {}
    if isinstance(checks, list):
        statuses = [item.get("status") for item in checks if isinstance(item, dict)]
        return {
            "overall": payload.get("overall") or _overall_status(statuses),
            "checks": checks,
        }

    normalized: list[dict[str, Any]] = []
    if isinstance(checks, dict):
        for key, value in checks.items():
            details = value if isinstance(value, dict) else {"value": value}
            ok = bool(details.get("ok"))
            label = key.replace("_", " ").title()
            normalized.append(
                {
                    "name": label,
                    "status": "ok" if ok else "error",
                    "message": _setup_check_message(key, details, ok),
                    "details": details,
                }
            )
    statuses = [item["status"] for item in normalized]
    return {
        "overall": payload.get("overall") or ("healthy" if payload.get("ok") else _overall_status(statuses)),
        "checks": normalized,
    }


def _setup_check_message(key: str, details: dict[str, Any], ok: bool) -> str:
    if key == "database":
        path = details.get("path") or "core database"
        return f"Core database ready at {path}" if ok else f"Core database is not ready at {path}"
    if key == "aws_credentials":
        identity = details.get("identity") or {}
        arn = identity.get("Arn") or identity.get("arn") or "unknown identity"
        return f"Authenticated as {arn}" if ok else f"AWS credentials unavailable: {details.get('error') or 'unknown error'}"
    if key == "service_token":
        path = details.get("path") or "service token"
        return f"Core service token ready at {path}" if ok else f"Core service token missing at {path}"
    return details.get("message") or ("Ready" if ok else details.get("error") or "Unavailable")


def _overall_status(statuses: list[str | None]) -> str:
    if "error" in statuses:
        return "unhealthy"
    if "warning" in statuses:
        return "degraded"
    return "healthy"


def _status_color(status: str) -> str:
    if status in {"ok", "healthy", "success"}:
        return "green"
    if status in {"warning", "degraded"}:
        return "yellow"
    if status in {"error", "unhealthy", "failed"}:
        return "red"
    return "cyan"


@setup_app.command(name="aws-profile")
def aws_profile():
    """Select AWS profile interactively."""
    import configparser
    from rich.prompt import Prompt

    config_path = os.path.expanduser("~/.aws/config")
    if not os.path.exists(config_path):
        console.print("[yellow]No ~/.aws/config found. Configure with: aws configure[/yellow]")
        return

    config = configparser.ConfigParser()
    config.read(config_path)

    profiles = []
    for section in config.sections():
        name = section.replace("profile ", "")
        region = config.get(section, "region", fallback="")
        sso = "Yes" if config.has_option(section, "sso_start_url") else ""
        profiles.append({"name": name, "region": region, "sso": sso})

    if not profiles:
        console.print("[yellow]No profiles found in ~/.aws/config[/yellow]")
        return

    table = Table(title="AWS Profiles", show_header=True, header_style="bold cyan")
    table.add_column("#", width=4)
    table.add_column("Profile")
    table.add_column("Region")
    table.add_column("SSO")

    for i, p in enumerate(profiles, 1):
        table.add_row(str(i), p["name"], p["region"], p["sso"])

    console.print(table)
    console.print()

    current = os.environ.get("AWS_PROFILE", "")
    if current:
        console.print(f"Current: [cyan]{current}[/cyan]")

    choice = Prompt.ask("Select profile number (or Enter to keep current)", default="")
    if choice and choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(profiles):
            selected = profiles[idx]["name"]
            console.print(f"\nSet with: [cyan]export AWS_PROFILE={selected}[/cyan]")
        else:
            console.print("[red]Invalid selection[/red]")


@setup_app.command()
def database():
    """Show database status and management options."""
    status = request_core("GET", "/api/v1/core/db/status", timeout=10.0)
    summary = request_core("GET", "/api/v1/resources/summary", timeout=10.0)
    db_path = status.get("db_path")

    console.print()
    console.print("[bold]Database Status[/bold]")
    console.print()
    console.print(f"  Path:     [cyan]{db_path}[/cyan]")
    console.print(f"  Runtime:  [cyan]bluearch-aws-core[/cyan]")

    if db_path and os.path.exists(db_path):
        size_mb = os.path.getsize(db_path) / (1024 * 1024)
        console.print(f"  Size:     [cyan]{size_mb:.1f} MB[/cyan]")
    else:
        console.print("  Size:     [yellow]Database not found[/yellow]")
        return

    console.print(f"  Tables:   [cyan]{status.get('table_count', 0)}[/cyan]")
    console.print(f"  Resources:       [cyan]{summary.get('total', 0)}[/cyan]")
    console.print(f"  Recommendations: [cyan]{_count_storage_records('bluearch', 'recommendations')}[/cyan]")
    console.print(f"  Accounts:        [cyan]{_count_storage_records('core', 'account-status')}[/cyan]")
    console.print()


def _submit_core_setup_job(
    path: str,
    *,
    payload: dict | None = None,
    action: str,
    timeout_seconds: int = 900,
) -> dict:
    """Submit a core-owned setup job and wait for completion."""
    job = request_core(
        "POST",
        path,
        service_token=True,
        json=payload or {},
        timeout=20.0,
    )
    job_id = job.get("job_id") or job.get("id")
    if not job_id:
        raise RuntimeError(f"bluearch-aws-core did not return a job id for {action}")
    console.print(f"[cyan]{action} started in bluearch-aws-core (job {job_id})[/cyan]")
    return _wait_for_core_setup_job(str(job_id), action, timeout_seconds=timeout_seconds)


def _wait_for_core_setup_job(job_id: str, action: str, *, timeout_seconds: int = 900) -> dict:
    deadline = time.time() + timeout_seconds
    last_message = None
    last_progress = None
    while time.time() < deadline:
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
        time.sleep(3)
    raise RuntimeError(f"Timed out waiting for bluearch-aws-core job {job_id}")


def _parse_csv_option(value: Optional[str]) -> list[str] | None:
    if not value:
        return None
    parsed = [item.strip() for item in value.split(",") if item.strip()]
    return parsed or None


def _print_core_stackset_status(status_payload: dict) -> None:
    if not status_payload.get("exists"):
        console.print(f"  [dim]StackSet '{STACKSET_NAME}' is not deployed[/dim]")
        return

    console.print(f"  StackSet:  [cyan]{status_payload.get('stackset_name') or STACKSET_NAME}[/cyan]")
    console.print(f"  Status:    [green]{status_payload.get('status', 'UNKNOWN')}[/green]")
    if status_payload.get("template_version"):
        console.print(f"  Version:   [cyan]{status_payload.get('template_version')}[/cyan]")

    instances = status_payload.get("instances") or []
    if not instances:
        console.print("  [dim]No stack instances deployed[/dim]")
        return

    table = Table(title=f"Stack Instances ({len(instances)})", show_header=True, header_style="bold cyan")
    table.add_column("Account")
    table.add_column("Region")
    table.add_column("Status")
    table.add_column("Reason", overflow="fold")
    for instance in instances:
        status = instance.get("status") or "UNKNOWN"
        style = "green" if status == "CURRENT" else ("yellow" if status == "OUTDATED" else "red")
        table.add_row(
            instance.get("account_id") or "-",
            instance.get("region") or "-",
            f"[{style}]{status}[/{style}]",
            instance.get("status_reason") or "-",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Assume Role (matches tag-manager setup assume-role)
# ---------------------------------------------------------------------------

ASSUME_ROLE_STACK_NAME = "BlueArchCLI-Role"
ASSUME_ROLE_ROLE_NAME = "BlueArchCLIRole"


@setup_app.command("assume-role")
def setup_assume_role(
    role_name: str = typer.Option(ASSUME_ROLE_ROLE_NAME, "--role-name", "-r", help="IAM role name to assume"),
    external_id: Optional[str] = typer.Option(None, "--external-id", "-e", help="External ID for role assumption"),
    disable: bool = typer.Option(False, "--disable", help="Disable assume role and use direct credentials"),
    delete_stack: bool = typer.Option(False, "--delete-stack", help="Also delete CloudFormation stack when disabling"),
    deploy: bool = typer.Option(False, "--deploy", "-d", help="Deploy CloudFormation stack to create the IAM role"),
    show_url: bool = typer.Option(False, "--show-url", "-u", help="Show CloudFormation quick-create URL"),
    status: bool = typer.Option(False, "--status", "-s", help="Show current assume role configuration"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompts"),
):
    """Configure assume-role authentication for BlueArch CLI.

    [green]Examples:[/green]
      bluearch-aws-ops setup assume-role --status          # Show current config
      bluearch-aws-ops setup assume-role --deploy           # Deploy IAM role via CloudFormation
      bluearch-aws-ops setup assume-role --show-url         # Get quick-create URL for manual deploy
      bluearch-aws-ops setup assume-role --disable          # Switch back to direct credentials
    """
    if status:
        _show_assume_role_status()
        return

    if show_url:
        _show_quick_create_url(role_name, external_id)
        return

    if disable:
        _disable_assume_role(delete_stack, force)
        return

    if deploy:
        _deploy_assume_role_stack(role_name, external_id, force)
        return

    _show_assume_role_status()
    console.print()
    console.print("[dim]Setup implementation is owned by bluearch-aws-core.[/dim]")
    console.print("  Deploy/update: [cyan]bluearch-aws-ops setup assume-role --deploy[/cyan]")
    console.print("  Manual URL:    [cyan]bluearch-aws-ops setup assume-role --show-url[/cyan]")
    console.print("  Disable:       [cyan]bluearch-aws-ops setup assume-role --disable[/cyan]")


def _show_assume_role_status():
    """Display current assume-role configuration."""
    from rich.table import Table

    try:
        status = request_core("GET", "/api/v1/assume-role/status", timeout=10.0)
    except Exception as exc:
        console.print(f"[red]bluearch-aws-core assume-role status unavailable: {exc}[/red]")
        raise typer.Exit(1)
    configs = _list_assume_role_configs()
    if not configs:
        console.print("[dim]No assume-role configurations found.[/dim]")
        console.print("[dim]Run [cyan]bluearch-aws-ops setup assume-role --deploy[/cyan] to set one up.[/dim]")

    if configs:
        table = Table(title="Assume Role Configurations", show_header=True, header_style="bold cyan")
        table.add_column("Account")
        table.add_column("Role Name")
        table.add_column("Active")
        table.add_column("Enabled")
        table.add_column("External ID")
        table.add_column("Last Used")

        for c in configs:
            external_id = c.get("external_id")
            ext_id = (external_id[:8] + "...") if external_id else "-"
            table.add_row(
                c.get("account_id") or "-",
                c.get("role_name") or "-",
                "[green]Yes[/green]" if c.get("is_active") else "[dim]No[/dim]",
                "[green]Yes[/green]" if c.get("enabled") else "[dim]No[/dim]",
                ext_id,
                _format_assume_role_time(c.get("last_used_at")),
            )
        console.print(table)

    console.print(
        f"\n  CloudFormation Stack: "
        f"[cyan]{status.get('stack_status') or 'Not deployed'}[/cyan]"
    )


def _show_quick_create_url(role_name: str, external_id: Optional[str]):
    """Show CloudFormation quick-create URL using the core-owned template registry."""
    from rich.prompt import Prompt
    from rich.panel import Panel

    template = _get_core_template_metadata("single_account_role.yaml")
    identity = _core_aws_identity()
    user_arn = identity.get("Arn") or identity.get("arn") or ""
    region = _current_region()

    console.print()
    console.print("[bold]Trust Mode Selection[/bold]")
    console.print("  1. [cyan]Current User[/cyan]    — Only your current IAM identity can assume the role")
    console.print("  2. [cyan]Any Principal[/cyan]   — Any IAM principal in this account can assume (recommended)")
    console.print("  3. [cyan]Specific ARN[/cyan]    — Only a specific IAM ARN can assume")
    console.print()
    choice = Prompt.ask("Select trust mode", choices=["1", "2", "3"], default="2")

    trust_mode = {"1": "CurrentUser", "2": "AnyPrincipal", "3": "SpecificArn"}[choice]
    specific_arn = ""
    if trust_mode == "SpecificArn":
        specific_arn = Prompt.ask("Specific IAM ARN")
    if trust_mode == "CurrentUser" and not user_arn:
        console.print("[yellow]bluearch-aws-core could not resolve the current user ARN; using AnyPrincipal instead.[/yellow]")
        trust_mode = "AnyPrincipal"

    # Build quick-create URL
    template_url = template.get("public_url") or (
        "https://raw.githubusercontent.com/bluearchio/bluearch-aws-core/main/"
        "bluearch_core/templates/single_account_role.yaml"
    )
    params = {
        "stackName": ASSUME_ROLE_STACK_NAME,
        "templateURL": template_url,
        "param_TrustedPrincipalMode": trust_mode,
        "param_RoleName": role_name,
    }
    if trust_mode == "CurrentUser" and user_arn:
        params["param_DeployingUserArn"] = user_arn
    if specific_arn:
        params["param_SpecificPrincipalArn"] = specific_arn
    if external_id:
        params["param_ExternalId"] = external_id

    url = (
        f"https://{region}.console.aws.amazon.com/cloudformation/home"
        f"?region={region}#/stacks/quickcreate?{urlencode(params)}"
    )

    console.print()
    console.print(Panel(
        f"[bold]Deploy the BlueArch IAM role:[/bold]\n\n"
        f"1. Open the URL below in your browser\n"
        f"2. Review the IAM resources being created\n"
        f"3. Check 'I acknowledge that AWS CloudFormation might create IAM resources'\n"
        f"4. Click 'Create stack'\n"
        f"5. Wait for CREATE_COMPLETE\n"
        f"6. Run: [cyan]bluearch-aws-ops setup assume-role[/cyan] to configure\n\n"
        f"[link={url}]{url}[/link]",
        title="CloudFormation Quick-Create",
        border_style="cyan",
    ))


def _deploy_assume_role_stack(role_name: str, external_id: Optional[str], force: bool):
    """Deploy the assume-role stack through bluearch-aws-core."""
    from rich.prompt import Prompt, Confirm

    console.print()
    console.print("[bold]Deploy Assume-Role Stack[/bold]")

    # Trust mode selection
    console.print()
    console.print("  1. [cyan]Current User[/cyan]    — Only your current identity")
    console.print("  2. [cyan]Any Principal[/cyan]   — Any principal in this account (recommended)")
    console.print()
    choice = Prompt.ask("Select trust mode", choices=["1", "2"], default="2")
    trust_mode = "CurrentUser" if choice == "1" else "AnyPrincipal"

    if not force:
        console.print()
        console.print(f"  Stack:      [cyan]{ASSUME_ROLE_STACK_NAME}[/cyan]")
        console.print(f"  Role:       [cyan]{role_name}[/cyan]")
        console.print(f"  Trust:      [cyan]{trust_mode}[/cyan]")
        console.print()
        if not Confirm.ask("Deploy this stack?", default=True):
            return

    try:
        result = _submit_core_setup_job(
            "/api/v1/assume-role/deploy",
            payload={
                "trust_mode": trust_mode,
                "specific_arn": None,
                "external_id": external_id,
                "role_name": role_name,
            },
            action="Assume-role deployment",
            timeout_seconds=900,
        )
    except Exception as e:
        console.print(f"[red]Failed to deploy assume-role through bluearch-aws-core: {e}[/red]")
        raise typer.Exit(1)

    if result.get("role_arn"):
        console.print(f"  Role ARN: [cyan]{result['role_arn']}[/cyan]")
    console.print()
    console.print("[green]Assume-role deployed and configured by bluearch-aws-core[/green]")


def _disable_assume_role(delete_stack: bool, force: bool):
    """Disable assume-role and optionally delete the CF stack."""
    from rich.prompt import Confirm

    if not force:
        msg = "Disable assume-role"
        if delete_stack:
            msg += " and delete CloudFormation stack"
        if not Confirm.ask(f"{msg}?", default=False):
            return

    try:
        result = _submit_core_setup_job(
            "/api/v1/assume-role/disable",
            payload={"delete_stack": delete_stack},
            action="Assume-role disable",
            timeout_seconds=600,
        )
    except Exception as e:
        console.print(f"[red]Failed to disable assume-role through bluearch-aws-core: {e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]{result.get('message') or 'Assume role disabled'}[/green]")


def _list_assume_role_configs() -> List[dict]:
    try:
        return request_core("GET", "/api/v1/assume-role/configs", timeout=10.0) or []
    except Exception as exc:
        console.print(f"[red]bluearch-aws-core assume-role configs unavailable: {exc}[/red]")
        raise typer.Exit(1)


def _get_core_template_metadata(template_name: str) -> dict:
    try:
        return request_core("GET", f"/api/v1/system/templates/{template_name}", timeout=10.0) or {}
    except Exception as exc:
        console.print(f"[red]bluearch-aws-core template registry unavailable: {exc}[/red]")
        raise typer.Exit(1)


def _core_aws_identity() -> dict:
    try:
        validation = request_core("GET", "/api/v1/setup/validate", timeout=15.0)
    except Exception:
        return {}
    checks = validation.get("checks") if isinstance(validation, dict) else {}
    if isinstance(checks, dict):
        aws = checks.get("aws_credentials") or {}
        identity = aws.get("identity") or {}
        return identity if isinstance(identity, dict) else {}
    if isinstance(checks, list):
        for item in checks:
            if not isinstance(item, dict):
                continue
            if str(item.get("name", "")).lower().replace(" ", "_") == "aws_credentials":
                details = item.get("details") or {}
                identity = details.get("identity") or {}
                return identity if isinstance(identity, dict) else {}
    return {}


def _current_region() -> str:
    return (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or os.environ.get("BLUEARCH_REGION")
        or "us-east-1"
    )


def _payload_from_storage_record(record: dict) -> dict:
    payload = dict(record.get("payload", record) or {})
    payload.setdefault("id", record.get("id") or record.get("record_key") or payload.get("id"))
    return payload


def _count_storage_records(namespace: str, collection: str) -> int:
    records = request_core(
        "GET",
        f"/api/v1/storage/{namespace}/{collection}",
        service_token=True,
        params=[("limit", 10000)],
        timeout=10.0,
    )
    return len(records or [])


def _format_assume_role_time(value) -> str:
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
# Multi-Account (matches tag-manager setup multi-account)
# ---------------------------------------------------------------------------

STACKSET_NAME = "BlueArchCLI-CrossAccount-Infrastructure"


@setup_app.command("multi-account")
def multi_account_setup(
    validate_only: bool = typer.Option(False, "--validate-only", help="Only validate prerequisites without deploying"),
    accounts: Optional[str] = typer.Option(None, "--accounts", help="Comma-separated list of account IDs"),
    organizational_units: Optional[str] = typer.Option(None, "--ous", help="Comma-separated list of OU IDs"),
    regions: Optional[str] = typer.Option(None, "--regions", help="Comma-separated list of regions"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompts"),
    clean: bool = typer.Option(False, "--clean", help="Delete existing StackSet and recreate from scratch"),
    update: bool = typer.Option(False, "--update", help="Update existing StackSet to latest template version"),
    complete: bool = typer.Option(False, "--complete", help="Complete setup: deploy, test, and enable all accounts"),
    remove: bool = typer.Option(False, "--remove", help="Remove all cross-account infrastructure"),
    status: bool = typer.Option(False, "--status", "-s", help="Show current StackSet status"),
):
    """Deploy cross-account infrastructure via AWS CloudFormation StackSets.

    [green]Examples:[/green]
      bluearch-aws-ops setup multi-account --status              # Check deployment status
      bluearch-aws-ops setup multi-account --complete             # Full automated setup
      bluearch-aws-ops setup multi-account --accounts 111,222     # Deploy to specific accounts
      bluearch-aws-ops setup multi-account --ous ou-abcd-1234     # Deploy to specific OUs
      bluearch-aws-ops setup multi-account --update               # Update to latest template
      bluearch-aws-ops setup multi-account --remove               # Remove all infrastructure
    """
    console.print()
    console.print("[bold]Multi-Account Setup[/bold]")
    console.print()

    try:
        validation = request_core("GET", "/api/v1/accounts/validate", timeout=15.0)
    except Exception as exc:
        console.print(f"[red]bluearch-aws-core account validation unavailable: {exc}[/red]")
        raise typer.Exit(1)

    current_account = validation.get("current_account_id") or "-"
    org_id = validation.get("organization_id") or "-"
    mgmt_account = validation.get("management_account_id") or "-"
    is_mgmt = validation.get("is_management_account")

    console.print(f"  Account:        [cyan]{current_account}[/cyan]")
    console.print(f"  Organization:   [cyan]{org_id}[/cyan]")
    console.print(f"  Management:     {'[green]Yes[/green]' if is_mgmt else '[dim]No[/dim]'}")
    console.print(
        f"  Delegated Admin: {'[green]Yes[/green]' if validation.get('is_delegated_admin') else '[dim]No[/dim]'}"
    )

    if not validation.get("can_deploy"):
        guidance = validation.get("guidance") or validation.get("error") or (
            "Run from the management account or a delegated CloudFormation StackSets admin."
        )
        console.print()
        console.print(f"[red]Prerequisites check failed: {guidance}[/red]")
        if mgmt_account != "-":
            console.print(f"[dim]Management account: {mgmt_account}[/dim]")
        raise typer.Exit(1)

    if validate_only:
        console.print()
        console.print("[green]Validation passed. Ready to deploy.[/green]")
        return

    if status:
        _show_stackset_status()
        return

    if remove:
        _remove_multi_account(force)
        return

    try:
        status_payload = request_core("GET", "/api/v1/accounts/status", timeout=15.0)
    except Exception as exc:
        console.print(f"[red]bluearch-aws-core account status unavailable: {exc}[/red]")
        raise typer.Exit(1)

    console.print()
    console.print("[bold]Existing Infrastructure[/bold]")
    _print_core_stackset_status(status_payload)

    if status_payload.get("exists") and not update and not clean and not complete:
        console.print()
        console.print("[dim]StackSet already deployed. Use --update to update or --clean to recreate.[/dim]")
        return

    if not force and not complete:
        from rich.prompt import Confirm

        console.print()
        targets = []
        if accounts:
            targets.append(f"Accounts: {accounts}")
        if organizational_units:
            targets.append(f"OUs: {organizational_units}")
        if regions:
            targets.append(f"Regions: {regions}")
        if not targets:
            targets.append("Target: All accounts in the organization")
        console.print("[bold]Deployment targets[/bold]")
        for target in targets:
            console.print(f"  - {target}")
        console.print()
        if not Confirm.ask("Deploy cross-account infrastructure?", default=True):
            return

    try:
        if update and status_payload.get("exists") and not clean:
            result = _submit_core_setup_job(
                "/api/v1/accounts/update",
                action="Cross-account update",
                timeout_seconds=1800,
            )
        else:
            result = _submit_core_setup_job(
                "/api/v1/accounts/deploy",
                payload={
                    "accounts": _parse_csv_option(accounts),
                    "organizational_units": _parse_csv_option(organizational_units),
                    "regions": _parse_csv_option(regions),
                    "force_recreate": clean,
                },
                action="Cross-account deployment",
                timeout_seconds=1800,
            )
    except Exception as exc:
        console.print(f"[red]Deployment failed through bluearch-aws-core: {exc}[/red]")
        raise typer.Exit(1)

    deployed_accounts = result.get("deployed_accounts") or []
    failed_accounts = result.get("failed_accounts") or []
    synced_accounts = result.get("synced_accounts")

    console.print()
    if failed_accounts:
        console.print(f"[yellow]Failed accounts: {', '.join(failed_accounts)}[/yellow]")
    if deployed_accounts:
        console.print(f"[green]StackSet deployed to {len(deployed_accounts)} account(s)[/green]")
    if synced_accounts is not None:
        console.print(f"[green]{synced_accounts} account target(s) synced in core storage[/green]")
    console.print("[green]Multi-account setup complete.[/green]")
    console.print("[dim]Run [cyan]bluearch-aws-ops setup multi-account --status[/cyan] to check deployment progress.[/dim]")


def _show_stackset_status():
    """Show StackSet deployment status."""
    try:
        status_payload = request_core("GET", "/api/v1/accounts/status", timeout=15.0)
    except Exception as exc:
        console.print(f"[red]bluearch-aws-core account status unavailable: {exc}[/red]")
        raise typer.Exit(1)
    _print_core_stackset_status(status_payload)


def _remove_multi_account(force: bool):
    """Remove all cross-account infrastructure."""
    from rich.prompt import Confirm

    if not force:
        if not Confirm.ask("[red]Remove ALL cross-account infrastructure?[/red]", default=False):
            return

    try:
        result = _submit_core_setup_job(
            "/api/v1/accounts/remove",
            action="Cross-account removal",
            timeout_seconds=1800,
        )
    except Exception as exc:
        console.print(f"[red]Failed to remove cross-account infrastructure through bluearch-aws-core: {exc}[/red]")
        raise typer.Exit(1)

    console.print()
    console.print(f"[green]{result.get('message') or 'Cross-account infrastructure removed.'}[/green]")


# ---------------------------------------------------------------------------
# Opt-In Hub (organization-wide AWS service enablement)
# ---------------------------------------------------------------------------


@setup_app.command("optin-hub")
def setup_optin_hub():
    """Configure AWS Opt-In services (Compute Optimizer, Cost Optimization Hub, etc).

    Opens an interactive UI to toggle AWS Organizations trusted services and
    manage per-account enrollment. Must be run from the management account
    or a delegated administrator.

    [green]Examples:[/green]
      bluearch-aws-ops setup optin-hub
    """
    from cli.opt_in_central import optin_hub
    optin_hub()


# ---------------------------------------------------------------------------
# Alarms (custom alarm management — lives in the web UI)
# ---------------------------------------------------------------------------


@setup_app.command("alarms")
def setup_alarms(
    list_all: bool = typer.Option(False, "--list", "-l", help="List configured custom alarms from the database."),
    delete: Optional[str] = typer.Option(None, "--delete", "-d", help="Delete an alarm by ID."),
    evaluate_all: bool = typer.Option(False, "--evaluate-all", help="Re-evaluate every enabled alarm now."),
):
    """Manage custom alarms that track recommendations.

    Alarms are created and edited in the web dashboard at
    [cyan]http://localhost:<port>/setup/alarms[/cyan]. Use this command
    for quick CLI actions (list, delete, force-evaluate) and pipelines.

    [green]Examples:[/green]
      bluearch-aws-ops setup alarms --list
      bluearch-aws-ops setup alarms --evaluate-all
      bluearch-aws-ops setup alarms --delete <alarm-id>
      bluearch-aws-core start --daemon # Then open /setup/alarms in browser
    """
    if delete:
        alarm = _get_alarm_config(delete)
        if not alarm:
            console.print(f"[yellow]No alarm found with id {delete}[/yellow]")
            raise typer.Exit(1)
        name = alarm.get("name") or delete
        _delete_alarm_config(delete)
        console.print(f"[green]Deleted alarm '{name}'[/green]")
        return

    if evaluate_all:
        from web.routers.alarms import _core_alarm_to_namespace, _core_count_matches, _send_notification

        alarms = [alarm for alarm in _list_alarm_configs() if alarm.get("enabled", True)]
        if not alarms:
            console.print("[dim]No enabled alarms to evaluate.[/dim]")
            return

        now = datetime.now(timezone.utc)
        triggered_count = 0
        for alarm in alarms:
            match_count, sample = _core_count_matches(alarm)
            alarm["last_evaluated_at"] = now.isoformat()
            alarm["last_match_count"] = match_count
            threshold = alarm.get("threshold") or 1
            if match_count >= threshold:
                ok, err = _send_notification(_core_alarm_to_namespace(alarm), match_count, sample)
                _create_alarm_event(
                    {
                        "alarm_id": alarm.get("id"),
                        "triggered_at": now.isoformat(),
                        "match_count": match_count,
                        "match_sample": sample,
                        "notification_sent": ok,
                        "notification_error": err,
                    }
                )
                alarm["last_triggered_at"] = now.isoformat()
                alarm["trigger_count"] = (alarm.get("trigger_count") or 0) + 1
                triggered_count += 1
                status_label = "[green]TRIGGERED[/green]" if ok else "[yellow]TRIGGERED (notify err)[/yellow]"
                console.print(f"  {status_label} {alarm.get('name') or alarm.get('id')} - {match_count} matches")
            else:
                console.print(
                    f"  [dim]{alarm.get('name') or alarm.get('id')} - "
                    f"{match_count} matches (below threshold)[/dim]"
                )
            if alarm.get("id"):
                _update_alarm_config(alarm["id"], alarm)
        console.print()
        console.print(f"[green]Evaluated {len(alarms)} alarm(s), {triggered_count} triggered[/green]")
        return

    # Default: list alarms
    alarms = _list_alarm_configs()

    if not alarms:
        console.print("[dim]No custom alarms configured yet.[/dim]")
        console.print(
            "[dim]Create one in the web UI: [cyan]bluearch-aws-core start --daemon[/cyan] then open "
            "[cyan]/setup/alarms[/cyan].[/dim]"
        )
        return

    table = Table(
        title=f"Custom Alarms ({len(alarms)})",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("ID", style="dim", overflow="fold", max_width=12)
    table.add_column("Name")
    table.add_column("Trigger")
    table.add_column("Threshold", justify="right")
    table.add_column("Enabled", justify="center")
    table.add_column("Last triggered")
    table.add_column("Total fires", justify="right")

    for a in alarms:
        alarm_id = str(a.get("id") or "")
        table.add_row(
            alarm_id[:8] + "..." if alarm_id else "-",
            a.get("name") or "-",
            a.get("trigger_type") or "-",
            str(a.get("threshold") or 1),
            "[green]Yes[/green]" if a.get("enabled", True) else "[dim]No[/dim]",
            _format_assume_role_time(a.get("last_triggered_at")),
            str(a.get("trigger_count") or 0),
        )
    console.print(table)
    console.print(
        "[dim]Create/edit alarms in the web UI at [cyan]/setup/alarms[/cyan] "
        "([cyan]bluearch-aws-core start --daemon[/cyan]).[/dim]"
    )


def _list_alarm_configs() -> List[dict]:
    records = request_core(
        "GET",
        "/api/v1/storage/bluearch/alarms",
        service_token=True,
        params=[("limit", 10000), ("order_by", "created_at"), ("descending", "true")],
        timeout=10.0,
    )
    return [_payload_from_storage_record(record) for record in records or []]


def _get_alarm_config(alarm_id: str) -> Optional[dict]:
    try:
        record = request_core(
            "GET",
            f"/api/v1/storage/bluearch/alarms/{alarm_id}",
            service_token=True,
            timeout=10.0,
        )
    except CoreRuntimeError as exc:
        if "404" in str(exc):
            return None
        raise
    return _payload_from_storage_record(record)


def _update_alarm_config(alarm_id: str, payload: dict) -> dict:
    record = request_core(
        "PUT",
        f"/api/v1/storage/bluearch/alarms/{alarm_id}",
        service_token=True,
        json={"payload": payload},
        timeout=10.0,
    )
    return _payload_from_storage_record(record)


def _delete_alarm_config(alarm_id: str) -> None:
    request_core(
        "DELETE",
        f"/api/v1/storage/bluearch/alarms/{alarm_id}",
        service_token=True,
        timeout=10.0,
    )


def _create_alarm_event(payload: dict) -> dict:
    record = request_core(
        "POST",
        "/api/v1/storage/bluearch/alarm-events",
        service_token=True,
        json={"payload": payload},
        timeout=10.0,
    )
    return _payload_from_storage_record(record)
