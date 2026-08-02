"""Scan command backed by bluearch-aws-core."""

from datetime import datetime, timezone
import time
from typing import Optional, List
from typer import Option


def scan(
    services: Optional[str] = Option(
        None,
        "--services",
        "-s",
        help="Comma-separated list of services to scan (e.g. ec2,rds,iam). Default: all.",
    ),
    regions: Optional[str] = Option(
        None,
        "--regions",
        "-r",
        help="Comma-separated list of regions to scan, or 'all'. Default: US regions.",
    ),
    skip_scan: bool = Option(
        False,
        "--skip-scan",
        help="Skip scanning if fresh data exists (< 5 min old by default). Uses data from either CLI.",
    ),
    skip_scan_age: int = Option(
        5,
        "--skip-scan-age",
        help="Maximum age in minutes for --skip-scan to accept existing data.",
    ),
    force: bool = Option(
        False,
        "--force",
        "-f",
        help="Force a new scan even if fresh data exists. Overrides --skip-scan.",
    ),
    cloud: bool = Option(
        False,
        "--cloud",
        help="Trigger cloud scan via Step Functions instead of local scan.",
    ),
):
    """
    Scan AWS resources through bluearch-aws-core and store results in the shared DB.

    [yellow]Runs locally — no CloudFormation deployment required.[/yellow]

    [green]Examples:[/green]
      bluearch-aws-ops scan                          # Scan all services, US regions
      bluearch-aws-ops scan -s ec2,rds               # Scan only EC2 and RDS
      bluearch-aws-ops scan -r us-east-1,eu-west-1   # Scan specific regions
      bluearch-aws-ops scan -r all                   # Scan all enabled regions
      bluearch-aws-ops scan --skip-scan              # Reuse recent data if available
      bluearch-aws-ops scan --force                  # Force rescan even if data is fresh
      bluearch-aws-ops scan --cloud                  # Trigger cloud scan via Step Functions
    """
    if cloud:
        _run_cloud_scan(services, regions)
        return

    if skip_scan and not force:
        from rich.console import Console

        console = Console()
        recent = _recent_core_scan(max_age_minutes=skip_scan_age)
        if recent:
            console.print(
                f"[green]Using resource data from BlueArch scan "
                f"({recent['age_minutes']} minutes ago, {recent['resources_found']} resources)[/green]"
            )
            return

    _run_core_scan(services, regions)


def _run_core_scan(services_str, regions_str):
    """Submit a scan to bluearch-aws-core and wait for completion."""
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from utils.core_client import request_core

    console = Console()

    service_list = _csv(services_str)
    region_list = _csv(regions_str)

    console.print()
    console.print("[bold]BlueArch Scan[/bold] [dim](bluearch-aws-core)[/dim]")
    console.print()

    job = request_core(
        "POST",
        "/api/v1/scans",
        json={
            "product": "bluearch",
            "services": service_list or [],
            "regions": region_list or [],
        },
        timeout=10.0,
    )
    job_id = job["id"]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(job.get("progress_message") or "Scanning...", total=100)
        while True:
            current = request_core("GET", f"/api/v1/scans/jobs/{job_id}", timeout=10.0)
            progress.update(
                task,
                completed=current.get("progress") or 0,
                description=current.get("progress_message") or current.get("message") or current.get("status", "Scanning"),
            )
            if current.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(1)

    if current.get("status") != "completed":
        console.print(f"[red]Scan failed:[/red] {current.get('error') or current.get('message') or current.get('status')}")
        raise SystemExit(1)

    result = current.get("result") or {}
    console.print(
        f"[green]Scan complete:[/green] {result.get('resources_found', current.get('total_resources', 0))} resources found."
    )


def _recent_core_scan(max_age_minutes: int) -> Optional[dict]:
    from utils.core_client import request_core

    try:
        rows = request_core("GET", "/api/v1/scans/history", timeout=10.0)
    except Exception:
        return None
    now = datetime.now(timezone.utc)
    for row in rows or []:
        if row.get("product") not in {None, "bluearch"} and row.get("source") not in {None, "bluearch"}:
            continue
        completed_at = _parse_datetime(row.get("completed_at"))
        if not completed_at:
            continue
        age_minutes = int((now - completed_at).total_seconds() // 60)
        if age_minutes <= max_age_minutes:
            result = row.get("result") or {}
            return {
                "age_minutes": age_minutes,
                "resources_found": result.get("resources_found", row.get("total_resources", 0)),
            }
    return None


def _parse_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _csv(value: Optional[str]) -> Optional[list[str]]:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Cloud scan (Step Functions)
# ---------------------------------------------------------------------------

def _get_sfn_arn() -> Optional[str]:
    """Resolve the Step Functions state machine ARN from cache or CloudFormation.

    Checks in order:
    1. The local diskcache for a previously resolved ARN
    2. CloudFormation stack outputs for the StateMachineArn key

    Returns:
        The state machine ARN string, or None if not found.
    """
    from utils.local_cache import LocalCacheManager, TTL_CFN_OUTPUTS

    cache = LocalCacheManager()

    # 1. Check diskcache
    cached_arn = cache.get("cfn:StateMachineArn")
    if cached_arn:
        return cached_arn

    # 2. Query CloudFormation for the stack output
    import boto3
    from botocore.exceptions import ClientError
    from utils.config import is_debug

    stack_name = (
        "bluearch-alerting-engine-cli-dev" if is_debug()
        else "bluearch-alerting-engine-cli"
    )

    try:
        cfn = boto3.client("cloudformation")
        response = cfn.describe_stacks(StackName=stack_name)
        outputs = {
            o["OutputKey"]: o["OutputValue"]
            for o in response["Stacks"][0].get("Outputs", [])
        }
        arn = outputs.get("StateMachineArn")
        if arn:
            cache.set("cfn:StateMachineArn", arn, ttl=TTL_CFN_OUTPUTS)
        return arn
    except (ClientError, KeyError, IndexError):
        return None


def _trigger_cloud_scan(
    services: Optional[List[str]],
    regions: Optional[List[str]],
) -> Optional[str]:
    """Trigger the Step Functions state machine for cloud-based scanning.

    Args:
        services: List of service names to scan, or None for all.
        regions: List of AWS regions to scan, or None for all.

    Returns:
        The execution ARN on success, or None if the SFN ARN could not be resolved.
    """
    import boto3
    import json

    sfn_arn = _get_sfn_arn()
    if not sfn_arn:
        return None

    sfn = boto3.client("stepfunctions")
    payload = {
        "services": services or [],
        "regions": regions or [],
    }
    response = sfn.start_execution(
        stateMachineArn=sfn_arn,
        input=json.dumps(payload),
    )
    return response.get("executionArn")


def _run_cloud_scan(services_str: Optional[str], regions_str: Optional[str]) -> None:
    """Parse inputs and trigger a cloud scan via Step Functions."""
    from rich.console import Console

    console = Console()
    console.print()
    console.print("[bold]BlueArch Cloud Scan[/bold]")
    console.print()
    console.print("Triggering cloud scan via Step Functions...")

    service_list = (
        [s.strip() for s in services_str.split(",")] if services_str else None
    )
    region_list = (
        [r.strip() for r in regions_str.split(",")] if regions_str else None
    )

    execution_arn = _trigger_cloud_scan(service_list, region_list)

    if execution_arn is None:
        console.print(
            "[bold red]Cloud scan requires deployed infrastructure. "
            "Run `bluearch-aws-ops setup wizard` first or use local scan (default).[/bold red]"
        )
        raise SystemExit(1)

    console.print(f"[green]Execution started:[/green] {execution_arn}")
    console.print()
    console.print(
        "[yellow]Check execution status in the AWS Step Functions console "
        "or run `bluearch-aws-ops scan` (local) to collect results.[/yellow]"
    )
    # TODO: sync S3 results into SQLite after execution completes
