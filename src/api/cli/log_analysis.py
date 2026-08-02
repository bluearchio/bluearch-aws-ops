"""`bluearch-aws-ops logs` — view log-analysis findings + AI root-cause analysis.

CloudWatch log scanning is part of the unified `bluearch-aws-ops scan` (runs as a
collector alongside ec2/rds/etc.), so this command group only exposes
read/analyze actions — not a separate scan trigger.
"""

from typing import Optional
from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from utils.display_utils import print_error, print_info, print_warning
from utils.error_handlers import handle_all_errors

log_analysis_app = typer.Typer(
    help=(
        "[bold]Log Analysis[/bold] -- view CloudWatch log error findings + AI root-cause analysis.\n\n"
        "[dim]Log scanning runs as part of [cyan]bluearch-aws-ops scan[/cyan].[/dim]\n\n"
        "[green]Examples:[/green]\n"
        "  bluearch-aws-ops logs errors                   View the latest scan's findings\n"
        "  bluearch-aws-ops logs analyze FINDING_ID       AI root-cause analysis on a finding\n"
    ),
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()


# ---------------------------------------------------------------------------
# logs errors
# ---------------------------------------------------------------------------

@log_analysis_app.command(name="errors")
@handle_all_errors
def errors_cmd(
    scan_id: Optional[str] = typer.Option(None, "--scan-id", help="View a specific scan (default: latest)"),
    linked: bool = typer.Option(False, "--linked", help="Show only resource-linked findings"),
    unlinked: bool = typer.Option(False, "--unlinked", help="Show only unlinked findings"),
    severity: Optional[str] = typer.Option(None, "--severity", help="Filter by severity"),
    resource_id: Optional[str] = typer.Option(None, "--resource-id", help="Filter to a specific resource"),
    limit: int = typer.Option(50, "--limit", help="Max rows to display"),
):
    """View log analysis findings."""
    if scan_id is None:
        latest = _latest_log_scan()
        if latest is None:
            print_warning("No log scans recorded yet. Run [cyan]bluearch-aws-ops scan[/cyan] first.")
            raise typer.Exit(0)
        scan_id = latest["id"]

    findings = _list_log_findings(
        scan_id=scan_id,
        linked=linked,
        unlinked=unlinked,
        severity=severity,
        resource_id=resource_id,
        limit=limit,
    )
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: (severity_order.get(f.get("severity"), 9), -(f.get("occurrence_count") or 0)))

    if not findings:
        print_info("No findings match the filters.")
        return

    _render_findings_table(findings[:limit], title=f"Findings for scan {scan_id[:8]}")


def _render_findings_table(findings, title: str):
    """Print findings as a Rich table, split linked vs unlinked."""
    linked = [f for f in findings if _field(f, "link_status") == "linked"]
    unlinked = [f for f in findings if _field(f, "link_status") != "linked"]

    if linked:
        t = Table(title=f"[bold]Linked[/bold] ({len(linked)})", show_lines=False)
        t.add_column("ID", style="dim")
        t.add_column("Sev")
        t.add_column("Resource")
        t.add_column("Type")
        t.add_column("Pattern", overflow="fold", max_width=60)
        t.add_column("Count", justify="right")
        t.add_column("Last Seen")
        for f in linked:
            t.add_row(
                str(_field(f, "id") or "")[:8],
                _severity_style(_field(f, "severity")),
                str(_field(f, "resource_id") or "")[:12] if _field(f, "resource_id") else "-",
                _field(f, "resource_type") or "-",
                _field(f, "error_pattern") or "",
                str(_field(f, "occurrence_count") or 0),
                _format_datetime(_field(f, "last_seen")),
            )
        console.print(t)

    if unlinked:
        t = Table(title=f"[bold]Unlinked[/bold] ({len(unlinked)})", show_lines=False)
        t.add_column("ID", style="dim")
        t.add_column("Sev")
        t.add_column("Log Group", overflow="fold", max_width=40)
        t.add_column("Pattern", overflow="fold", max_width=60)
        t.add_column("Count", justify="right")
        t.add_column("Last Seen")
        for f in unlinked:
            t.add_row(
                str(_field(f, "id") or "")[:8],
                _severity_style(_field(f, "severity")),
                _field(f, "log_group_name") or "",
                _field(f, "error_pattern") or "",
                str(_field(f, "occurrence_count") or 0),
                _format_datetime(_field(f, "last_seen")),
            )
        console.print(t)


def _severity_style(severity: Optional[str]) -> str:
    colors = {"critical": "red", "high": "orange3", "medium": "yellow", "low": "blue"}
    color = colors.get(severity or "", "white")
    return f"[{color}]{(severity or '?').upper()}[/{color}]"


def _list_storage(collection: str, *, filters: list[tuple[str, str]] | None = None, limit: int = 100, order_by: str | None = None) -> list[dict]:
    from utils.core_client import request_core

    params: list[tuple[str, str | int]] = [("limit", limit), ("descending", "true")]
    if order_by:
        params.append(("order_by", order_by))
    for field, value in filters or []:
        if value is not None:
            params.append(("filter", f"{field}={value}"))
    rows = request_core(
        "GET",
        f"/api/v1/storage/bluearch/{collection}",
        service_token=True,
        params=params,
        timeout=10.0,
    )
    return [row.get("payload", row) for row in rows or []]


def _latest_log_scan() -> Optional[dict]:
    rows = _list_storage("log-scans", limit=1, order_by="started_at")
    return rows[0] if rows else None


def _list_log_findings(
    *,
    scan_id: str,
    linked: bool,
    unlinked: bool,
    severity: Optional[str],
    resource_id: Optional[str],
    limit: int,
) -> list[dict]:
    filters = [("scan_id", scan_id)]
    if linked:
        filters.append(("link_status", "linked"))
    if unlinked:
        filters.append(("link_status", "unlinked"))
    if severity:
        filters.append(("severity", severity))
    if resource_id:
        filters.append(("resource_id", resource_id))
    return _list_storage("log-findings", filters=filters, limit=max(limit, 100), order_by="detected_at")


def _field(item, name: str):
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _format_datetime(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.isoformat(timespec="seconds")
        except ValueError:
            return value
    return "-"


def _resolve_log_finding_id(value: str) -> Optional[str]:
    if len(value) >= 32:
        rows = _list_storage("log-findings", filters=[("id", value)], limit=1)
        if rows:
            return rows[0].get("id")
    rows = _list_storage("log-findings", limit=10000, order_by="detected_at")
    for row in rows:
        row_id = str(row.get("id") or "")
        if row_id == value or row_id.startswith(value):
            return row_id
    return None


# ---------------------------------------------------------------------------
# logs analyze
# ---------------------------------------------------------------------------

@log_analysis_app.command(name="analyze")
@handle_all_errors
def analyze_cmd(
    finding_id: str = typer.Argument(..., help="Finding ID (from `bluearch-aws-ops logs errors`)"),
    model: str = typer.Option("sonnet", "--model", "-m", help="Bedrock model alias: haiku / sonnet / opus"),
    region: Optional[str] = typer.Option(None, "--region", "-r", help="AWS region for Bedrock + Logs"),
):
    """
    Run AI root-cause analysis on a single finding.

    Fetches up to 50 sample log lines, sends them to Bedrock, and persists
    the response on the finding so it's available in future views.
    """
    from modules.log_analysis import LogAnalysisService

    full_id = _resolve_log_finding_id(finding_id)
    if not full_id:
        print_error(f"Finding '{finding_id}' not found.")
        raise typer.Exit(1)

    print_info(f"Analyzing finding {full_id[:8]} with {model}...")
    service = LogAnalysisService(region=region)
    analysis = service.analyze_finding(full_id, model_alias=model)

    console.print(Panel(
        analysis,
        title=f"[bold]AI Analysis[/bold] — {full_id[:8]}",
        border_style="cyan",
        padding=(1, 2),
    ))
