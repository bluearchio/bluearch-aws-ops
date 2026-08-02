import os
import re
import subprocess
from pathlib import Path

from typer import Option


CORE_FORMULA = "bluearchio/tap/bluearch-aws-core"
OPS_FORMULA = "bluearchio/tap/bluearch-aws-ops"
PUBLIC_FORMULAS = frozenset({CORE_FORMULA, OPS_FORMULA})
PUBLIC_OPS_EXECUTABLE = "bluearch-aws-ops"
PUBLIC_OPS_VERSION_RE = re.compile(
    rf"{re.escape(PUBLIC_OPS_EXECUTABLE)} [0-9]+\.[0-9]+\.[0-9]+"
)


def _trust_homebrew_formula(formula: str) -> bool:
    """Trust one exact public formula before any Homebrew mutation."""
    result = subprocess.run(
        ["brew", "trust", "--formula", formula],
        capture_output=False,
        text=True,
        timeout=60,
    )
    return result.returncode == 0


def _run_trusted_homebrew_formula(operation: str, formula: str, *, timeout: int = 300) -> bool:
    """Run one allowed install/upgrade only after its exact formula is trusted."""
    if operation not in {"install", "upgrade"} or formula not in PUBLIC_FORMULAS:
        raise ValueError("Unsupported Homebrew formula mutation")
    formulas_to_trust = (CORE_FORMULA, OPS_FORMULA) if formula == OPS_FORMULA else (formula,)
    for required_formula in formulas_to_trust:
        if not _trust_homebrew_formula(required_formula):
            return False
    result = subprocess.run(
        ["brew", operation, formula],
        capture_output=False,
        text=True,
        timeout=timeout,
    )
    return result.returncode == 0


def _trust_required_homebrew_formulas() -> bool:
    """Trust Core and then Ops before loading any Ops tap metadata."""
    for formula in (CORE_FORMULA, OPS_FORMULA):
        if not _trust_homebrew_formula(formula):
            return False
    return True


def _run_trusted_homebrew_outdated(formula: str = OPS_FORMULA):
    """Query the exact Ops formula only after Core and Ops trust succeeds."""
    if formula != OPS_FORMULA:
        raise ValueError("Unsupported Homebrew formula query")
    if not _trust_required_homebrew_formulas():
        raise RuntimeError("Could not trust the required Core and Ops formulas")
    result = subprocess.run(
        ["brew", "outdated", formula],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Homebrew outdated check failed for {formula}{suffix}")
    return result


def _installed_public_core_satisfies(required_core_version: str) -> bool:
    """Execute the resolved public Core and enforce its minimum version."""
    from utils.core_client import core_version_satisfies, get_installed_core_version

    return core_version_satisfies(get_installed_core_version(), required_core_version)


def _update_homebrew_core(required_core_version: str) -> bool:
    """Install or upgrade Core, then verify its exact public runtime identity."""
    installed = subprocess.run(
        ["brew", "list", "--versions", "bluearch-aws-core"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    operation = "upgrade" if installed.returncode == 0 and installed.stdout.strip() else "install"
    succeeded = _run_trusted_homebrew_formula(operation, CORE_FORMULA)
    if not succeeded and operation == "upgrade":
        succeeded = _run_trusted_homebrew_formula("install", CORE_FORMULA)
    return succeeded and _installed_public_core_satisfies(required_core_version)


def _perform_homebrew_update(required_core_version: str) -> bool:
    """Update Homebrew and Core safely before upgrading the public Ops formula."""
    if not _trust_required_homebrew_formulas():
        return False
    update_result = subprocess.run(
        ["brew", "update"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if update_result.returncode != 0:
        return False
    if not _update_homebrew_core(required_core_version):
        return False
    return _run_trusted_homebrew_formula("upgrade", OPS_FORMULA)


def _resolve_public_homebrew_binary(path: Path) -> Path | None:
    """Resolve a Homebrew link without executing legacy or renamed targets."""
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    try:
        cellar_index = resolved.parts.index("Cellar")
        formula_name = resolved.parts[cellar_index + 1]
    except (ValueError, IndexError):
        return None
    if (
        resolved.name != PUBLIC_OPS_EXECUTABLE
        or formula_name != PUBLIC_OPS_EXECUTABLE
        or not resolved.is_file()
        or not os.access(resolved, os.X_OK)
    ):
        return None
    return resolved


def detect_homebrew_installation(locations: dict[str, Path] | None = None) -> dict:
    """Return info only for an exact, executable public Ops Homebrew target."""
    locations = locations or {
        "homebrew_arm": Path("/opt/homebrew/bin/bluearch-aws-ops"),
        "homebrew_intel": Path("/usr/local/bin/bluearch-aws-ops"),
    }
    for install_type, path in locations.items():
        resolved = _resolve_public_homebrew_binary(path)
        if resolved is None:
            continue

        version = "unknown"
        try:
            result = subprocess.run(
                [str(resolved), "--version"], capture_output=True, text=True, timeout=10
            )
            lines = result.stdout.splitlines()
            if result.returncode == 0 and lines and PUBLIC_OPS_VERSION_RE.fullmatch(lines[0]):
                version = lines[0]
        except Exception:
            pass

        legacy_binary = Path.home() / ".local" / "bin" / "bluearch"
        return {
            "installed": True,
            "binary_path": str(path),
            "resolved_binary_path": str(resolved),
            "version": version,
            "install_type": install_type,
            "conflict": legacy_binary.exists(),
            "curl_binary_path": str(legacy_binary) if legacy_binary.exists() else None,
        }
    return {"installed": False}

def delete():
    """
    [deprecated] Delete the CloudFormation stack.

    This command is deprecated. BlueArch CLI no longer requires a CloudFormation
    deployment. Use 'bluearch-aws-ops scan' for local scanning instead.
    """
    from utils.display_utils import print_warning
    print_warning(
        "The 'delete' command is deprecated. BlueArch CLI no longer requires "
        "a CloudFormation deployment. All scanning runs locally via 'bluearch-aws-ops scan'."
    )
    return
    # Legacy CloudFormation logic preserved below for reference
    from aws.misc.error_handlings import error_handler

    def execute_delete():
        try:
            from aws.wrappers.cloudformation import CloudFormation
            from rich.console import Console
            from rich.prompt import Prompt

            console = Console()

            console.print("Checking if the CloudFormation stack exists...")
            cloudformation = CloudFormation(region_name="us-east-1")
            if not cloudformation.check_stack_exists():
                console.print(
                    "[yellow]The CloudFormation stack does not exist. No action needed.[/yellow]"
                )
            else:
                console.print("The CloudFormation stack exists.")

                # Confirm the deletion
                delete_confirmed = Prompt.ask(
                    "[blue]Are you sure you want to delete the CloudFormation stack?[/blue]", choices=["yes", "no"], default="no"
                ) == "yes"

                if delete_confirmed:
                    success = cloudformation.delete_stack()
                    if success:
                        from utils.cache import delete_cache

                        console.print(
                            "[green]CloudFormation stack deleted successfully.[/green]"
                        )
                        delete_cache()
                    else:
                        console.print(
                            "[red]Failed to delete the CloudFormation stack.[/red]"
                        )
                else:
                    console.print("Stack deletion aborted.")

        except Exception as e:
            error_handler.handle_error(e)
    execute_delete()


def show_accounts_and_regions():
    """
    Displays the collected Account IDs and Regions from bluearch-aws-core.
    """
    from rich.console import Console
    from rich.table import Table
    from db.crud import DatabaseManager

    console = Console()
    accounts = DatabaseManager().get_accounts_and_regions()

    if not accounts:
        console.print("[yellow]No accounts found. Run [cyan]bluearch-aws-ops scan[/cyan] first.[/yellow]")
        return

    table = Table(title="Accounts & Regions", show_header=True, header_style="bold cyan")
    table.add_column("Account ID")
    table.add_column("Name")
    table.add_column("Regions")

    for account_id, account in sorted(
        accounts.items(),
        key=lambda item: item[1].get("account_name") or item[0],
    ):
        regions = account.get("regions") if isinstance(account.get("regions"), list) else []
        table.add_row(account_id, account.get("account_name") or "Unknown", ", ".join(regions))

    console.print(table)

def update(
    check: bool = Option(False, "--check", help="Check for updates without installing"),
    force: bool = Option(False, "--force", "-f", help="Force update without confirmation"),
    yes: bool = Option(False, "--yes", "-y", help="Auto-confirm update if a newer version is available"),
    development: bool = Option(
        False, "--development", "--dev",
        help="Download from development channel instead of production",
    ),
):
    """
    Update BlueArch CLI to the latest version.

    The update method is detected automatically from your installation:
      - Homebrew: uses 'brew upgrade bluearchio/tap/bluearch-aws-ops'
      - Source install: reinstall from the local checkout

    [green]Examples:[/green]
      bluearch-aws-ops update              # Update to latest version
      bluearch-aws-ops update --check      # Check for updates without installing
      bluearch-aws-ops update --force      # Update without confirmation
      bluearch-aws-ops update --dev        # Development channel (curl only)
      bluearch-aws-ops update --yes        # Unattended (skip if already up to date)
    """
    from rich.console import Console
    from rich.prompt import Confirm
    from rich.markup import escape
    import typer

    from aws.misc.error_handlings import error_handler

    console = Console()
    PROD_INSTALL_URL = f"brew install {OPS_FORMULA}"
    DEV_INSTALL_URL = "pipx install -e ../bluearch-aws-ops --force"
    CORE_REQUIREMENT_KEYS = (
        "minimum_core_version",
        "minimum_bluearch_core_version",
        "bluearch_core_min_version",
        "required_core_version",
    )

    def perform_homebrew_update(required_core_version: str) -> bool:
        console.print("\n[blue]Updating via Homebrew...[/blue]")
        console.print("[dim]Updating Homebrew tap...[/dim]")
        succeeded = _perform_homebrew_update(required_core_version)
        if not succeeded:
            console.print("[red]bluearch-aws-core update failed. BlueArch CLI update was not started.[/red]")
        return succeeded

    def perform_core_install(required_core_version: str, development_channel: bool) -> bool:
        from utils.core_client import core_install_url

        install_url = core_install_url(development_channel)
        console.print(f"\n[blue]Ensuring bluearch-aws-core >= {required_core_version}...[/blue]")
        if not development_channel:
            succeeded = _run_trusted_homebrew_formula("install", CORE_FORMULA)
            return succeeded and _installed_public_core_satisfies(required_core_version)
        cmd = install_url
        console.print(f"[dim]Executing: {cmd}[/dim]")
        result = subprocess.run(cmd.split(), capture_output=False, text=True)
        return result.returncode == 0

    def _required_core_version(update_info: dict | None) -> str:
        from utils.core_client import MINIMUM_CORE_VERSION

        if update_info:
            for key in CORE_REQUIREMENT_KEYS:
                value = update_info.get(key)
                if value:
                    return str(value).lstrip("v")
        return MINIMUM_CORE_VERSION

    def _print_core_requirement(required_core_version: str) -> None:
        from utils.core_client import get_installed_core_version, core_version_satisfies

        installed = get_installed_core_version()
        installed_label = installed or "not installed"
        status = "ok" if core_version_satisfies(installed, required_core_version) else "update required"
        console.print(f"[blue]Required BlueArch Core:[/blue] >= {required_core_version}")
        console.print(f"[blue]Installed BlueArch Core:[/blue] {installed_label} ({status})")

    def _core_update_required(required_core_version: str) -> bool:
        from utils.core_client import get_installed_core_version, core_version_satisfies

        return not core_version_satisfies(get_installed_core_version(), required_core_version)

    def _sort_updates(updates: list[dict] | None) -> list[dict] | None:
        if not updates:
            return updates
        try:
            return sorted(
                updates,
                key=lambda u: _parse_version(u.get("version", "0")),
                reverse=True,
            )
        except Exception:
            return updates

    def _parse_version(v: str) -> tuple:
        """Parse 'v0.10.1' / '0.10.1' into a comparable tuple. Unparseable segments become 0."""
        if not v:
            return (0,)
        v = str(v).lstrip("v").strip()
        parts = []
        for segment in v.split("."):
            try:
                parts.append(int(segment))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    def execute_update():
        try:
            from aws.misc.version_controller import CURRENT_VERSION, get_updates

            channel = "development" if development else "production"
            install_url = DEV_INSTALL_URL if development else PROD_INSTALL_URL

            console.print(f"[blue]Current version:[/blue] {CURRENT_VERSION}")
            console.print(f"[blue]Update channel:[/blue] {channel}")

            updates = None
            try:
                updates = _sort_updates(get_updates())
            except Exception as e:
                console.print(f"[yellow]Could not check release metadata: {escape(str(e))}[/yellow]")
            latest_update = updates[0] if updates else None
            required_core_version = _required_core_version(latest_update)
            _print_core_requirement(required_core_version)

            homebrew = detect_homebrew_installation()
            if homebrew["installed"]:
                console.print("\n[yellow][NOTICE] BlueArch is installed via Homebrew[/yellow]")
                if homebrew.get("binary_path"):
                    console.print(f"[dim]  Binary: {homebrew['binary_path']}[/dim]")
                if homebrew.get("version"):
                    console.print(f"[dim]  Version: {homebrew['version']}[/dim]")

                if homebrew.get("conflict"):
                    console.print("\n[yellow][WARNING] Multiple installations detected![/yellow]")
                    console.print(f"[dim]  Curl binary also exists at: {homebrew['curl_binary_path']}[/dim]")

                if development:
                    console.print("\n[yellow][WARNING] Development channel not available via Homebrew[/yellow]")
                    console.print("[dim]Homebrew only tracks production releases.[/dim]")
                    console.print("[dim]To use dev versions:[/dim]")
                    console.print("[dim]  brew uninstall bluearchio/tap/bluearch-aws-ops[/dim]")
                    console.print(f"[dim]  {DEV_INSTALL_URL}[/dim]")
                    return

                if check:
                    console.print("\n[blue]Checking for Homebrew updates...[/blue]")
                    try:
                        result = _run_trusted_homebrew_outdated()
                        if result.stdout.strip():
                            console.print("[yellow]Update available via Homebrew[/yellow]")
                            console.print(f"\n[cyan]brew trust --formula {CORE_FORMULA}[/cyan]")
                            console.print(f"[cyan]brew trust --formula {OPS_FORMULA}[/cyan]")
                            console.print(f"[cyan]brew upgrade {CORE_FORMULA} {OPS_FORMULA}[/cyan]")
                        else:
                            console.print("[green]Already on latest Homebrew version![/green]")
                    except Exception as e:
                        console.print(f"[red]Could not check Homebrew updates: {escape(str(e))}[/red]")
                        raise typer.Exit(1)
                    return

                console.print("\n[blue]Homebrew is the recommended update method for your installation.[/blue]")
                if not force and not yes:
                    prompt = (
                        "\nUpdate BlueArch Core and BlueArch CLI via Homebrew "
                        "(brew upgrade/install bluearch-aws-core, then brew upgrade bluearch-aws-ops)?"
                    )
                    if not Confirm.ask(prompt, default=True):
                        console.print(f"\n[dim]Update cancelled. First run: brew trust --formula {CORE_FORMULA}[/dim]")
                        console.print(f"[dim]Then run: brew trust --formula {OPS_FORMULA}[/dim]")
                        console.print(f"[dim]Then run: brew upgrade {CORE_FORMULA} {OPS_FORMULA}[/dim]")
                        return

                if perform_homebrew_update(required_core_version):
                    console.print("\n[green]Update completed successfully![/green]")
                    console.print("\nRun [cyan]bluearch-aws-ops --version[/cyan] to verify the new version.")
                else:
                    console.print(f"[red]Homebrew update failed. Trust {CORE_FORMULA} and {OPS_FORMULA} individually, then retry.[/red]")
                    raise typer.Exit(1)
                return

            if not updates:
                console.print("[green]You are already up to date![/green]")
                if check:
                    return
                if _core_update_required(required_core_version):
                    if force or yes or Confirm.ask("BlueArch Core must be updated for this BlueArch CLI version. Update core now?", default=True):
                        if not perform_core_install(required_core_version, development):
                            console.print("[red]BlueArch Core update failed.[/red]")
                            raise typer.Exit(1)
                    return
                if yes:
                    return
                if not force and not check:
                    if not Confirm.ask("Continue with installation anyway?", default=False):
                        console.print("Update cancelled.")
                        return
            else:
                latest = updates[0]
                console.print(
                    f"\n[yellow]Latest version available:[/yellow] "
                    f"[green]{latest['version']}[/green] ({latest.get('date', '')})"
                )
                message = latest.get("message", "") or ""
                if message.strip():
                    message = message.replace("\\n", "\n").strip('"').strip()
                    if message:
                        console.print(f"[dim]{message}[/dim]")

            if check:
                if updates:
                    console.print("\nTo update: [cyan]bluearch-aws-ops update[/cyan]")
                return

            if not force and not yes:
                console.print("\n[yellow]This will update BlueArch CLI to the latest version.[/yellow]")
                console.print("[dim]This will:[/dim]")
                console.print(f"[dim]  - Install or update bluearch-aws-core to >= {required_core_version}[/dim]")
                console.print("[dim]  - Download and install the latest binary[/dim]")
                console.print("[dim]  - Preserve your database (automatic backup)[/dim]")
                console.print("[dim]  - Run any necessary database migrations[/dim]")
                console.print("")
                if not Confirm.ask("Continue with update?", default=True):
                    console.print("Update cancelled.")
                    return

            if not perform_core_install(required_core_version, development):
                console.print("[red]BlueArch Core update failed. BlueArch CLI update was not started.[/red]")
                raise typer.Exit(1)

            console.print(f"\n[blue]Downloading and installing latest {channel} version...[/blue]")
            cmd = install_url
            console.print(f"[dim]Executing: {cmd}[/dim]")
            if development:
                result = subprocess.run(cmd.split(), capture_output=False, text=True)
                succeeded = result.returncode == 0
            else:
                succeeded = _run_trusted_homebrew_formula("install", OPS_FORMULA)

            if succeeded:
                console.print("\n[green]Update completed successfully![/green]")
                console.print("\n[dim]Database migrations are handled automatically during installation.[/dim]")
                console.print(
                    "\nYou may need to restart your terminal or run "
                    "[cyan]source ~/.bashrc[/cyan] (or [cyan]source ~/.zshrc[/cyan])"
                )
                console.print("\nRun [cyan]bluearch-aws-ops --version[/cyan] to verify the new version.")
            else:
                console.print("[red]Update failed. Please check the output above for details.[/red]")
                console.print("[red]You can also try running the installation manually:[/red]")
                console.print(f"  [cyan]{cmd}[/cyan]")
                raise typer.Exit(1)

        except typer.Exit:
            raise
        except KeyboardInterrupt:
            console.print("\n[yellow]Update cancelled by user.[/yellow]")
            raise typer.Exit(1)
        except Exception as e:
            try:
                error_handler.handle_error(e)
            except Exception:
                console.print(f"[red]Update failed: {escape(str(e))}[/red]")

    execute_update()

def deploy(add_accounts: bool = Option(False, "--add-accounts", help="Add more accounts to an existing manual deployment")):
    """
    [deprecated] Start the CloudFormation configuration workflow.

    This command is deprecated. BlueArch CLI no longer requires a CloudFormation
    deployment. Use 'bluearch-aws-ops scan' for local scanning instead.
    If you need cross-account setup, use 'bluearch-aws-ops setup multi-account'.
    """
    from utils.display_utils import print_warning
    print_warning(
        "The 'deploy' command is deprecated. BlueArch CLI no longer requires "
        "a CloudFormation deployment. Use 'bluearch-aws-ops scan' for local scanning, "
        "or 'bluearch-aws-ops setup multi-account' for cross-account configuration."
    )
    return
    # Legacy CloudFormation logic preserved below for reference
    from utils.logger_config import log
    def execute_deploy():
        try:
            from aws.wrappers.cloudformation import CloudFormation
            from aws.misc import display
            from rich.console import Console
            from rich.prompt import Prompt
            from aws.misc.error_handlings import error_handler
            from utils.cache import delete_cache
            import re
            console = Console()

            console.print("Checking if the CloudFormation stack is already created...")
            delete_cache()
            cloudformation = CloudFormation(region_name="us-east-1")

            # Handle add_accounts flag
            if add_accounts:
                if not cloudformation.check_stack_exists():
                    console.print("[red]No existing BlueArch deployment found. Please deploy first.[/red]")
                    return
                
                from commons.globals import DEPLOY_MODE
                if DEPLOY_MODE != 'manual':
                    console.print("[red]Adding accounts is only supported for manual deployments.[/red]")
                    return

                from aws.misc.display import display_manual_instructions_workflow
                from aws.wrappers.clients import AWSClients
                from db.crud import DatabaseManager

                # Get new accounts through manual workflow
                new_account_ids = display_manual_instructions_workflow()
                if not new_account_ids:
                    return

                # Validate and filter account IDs
                valid_account_ids = []
                with console.status("[bold blue]Validating roles...") as status:
                    for acc_id, is_valid in AWSClients.validate_manual_deployment_role_assumptions(new_account_ids):
                        if is_valid:
                            console.print(f"[green]- {acc_id} (Role validated successfully)[/green]")
                            valid_account_ids.append(acc_id)
                        else:
                            console.print(f"[red]- {acc_id} (Unable to assume role - please ensure the role is created)[/red]")

                if not valid_account_ids:
                    console.print("[red]No valid accounts found to add.[/red]")
                    return

                # Save account IDs to database
                db_manager = DatabaseManager()
                db_manager._account_ids = valid_account_ids
                db_manager.populate_accounts_and_regions()

                console.print("[green]Successfully added new accounts to BlueArch![/green]")
                print(f"\n\n{display.display_bluearch_ascii_art()}")
                return

            # Original deployment logic
            if cloudformation.check_stack_exists():
                console.print(
                    "The CloudFormation stack is already created. No action needed."
                )
            else:
                console.print(
                    "The CloudFormation stack is not created. Starting Deployment workflow..."
                )
                
                auto_mode = Prompt.ask("[blue]Do you want to deploy in auto mode?[/blue]", choices=["yes", "no"], default="yes")
                
                # Get workspace name first (needed for both modes)
                workspace = Prompt.ask(
                    "[blue]Enter the workspace name[/blue]"
                )

                workspace_pattern = r"^[a-z]{1,16}$"
                while not re.match(workspace_pattern, workspace):
                    console.print(
                        "[red]Invalid workspace name. It must contain only lowercase letters (a to z) and be up to 16 characters.[/red]"
                    )
                    workspace = Prompt.ask(
                        "[bold blue]Enter the workspace name[/bold blue]"
                    )

                if auto_mode == "no":
                    from aws.misc.display import display_manual_instructions_workflow
                    from db.crud import DatabaseManager
                    
                    account_ids = display_manual_instructions_workflow()
                    
                    # Review the configuration
                    console.print("\nReview the configuration:")
                    console.print(f"Manual Mode with following accounts:")
                    for acc_id in account_ids:
                        console.print(f"- {acc_id}")
                    
                    # Confirm the deployment
                    deploy = Prompt.ask("[blue]Do you want to proceed with the deployment?[/blue]", choices=["yes", "no"], default="no")

                    if deploy == "yes":
                        # Deploy stack only in the current account
                        response = cloudformation.deploy_stack(workspace=workspace, auto_mode=auto_mode)
                        if response:
                            console.print("Monitoring stack creation...")
                            cloudformation.monitor_stack_creation()

                            if cloudformation.check_stack_status():
                                # Wait for CloudFormation outputs to be available
                                import time
                                console.print("[yellow]Waiting for CloudFormation outputs to be available...[/yellow]")
                                time.sleep(5)  # Give CF a moment to settle
                                
                                # Force refresh and cache all required outputs
                                from commons.globals import CloudFormationOutputs
                                from utils.cache_manager import CLOUDFORMATION_CACHE
                                
                                try:
                                    cfn_outputs = CloudFormationOutputs()
                                    outputs = cfn_outputs.get_cfn_outputs([
                                        'RoleName', 
                                        'AccTableName', 
                                        'RecTableName',
                                        'Region'
                                    ])
                                    
                                    # Explicitly cache each output
                                    for key, value in outputs.items():
                                        try:
                                            CLOUDFORMATION_CACHE.set(f'cfn_output_{key}', value)
                                        except Exception as e:
                                            log.error(f"Failed to cache {key}: {str(e)}")
                                    
                                    # Verify cached values
                                    acc_table = outputs.get('AccTableName')  # Use direct outputs instead of cache
                                    rec_table = outputs.get('RecTableName')  # Use direct outputs instead of cache
                                    
                                    if not acc_table or not rec_table:
                                        console.print("[red]Failed to get required table names from CloudFormation[/red]")
                                        return
                                    
                                    console.print("[green]Successfully retrieved CloudFormation outputs[/green]")
                                    
                                except Exception as e:
                                    console.print(f"[red]Failed to get CloudFormation outputs: {str(e)}[/red]")
                                    return
                                
                                # Validate and filter account IDs
                                from aws.wrappers.clients import AWSClients
                                valid_account_ids = []
                                with console.status("[bold blue]Validating roles...") as status:
                                    for acc_id, is_valid in AWSClients.validate_manual_deployment_role_assumptions(account_ids):
                                        if is_valid:
                                            console.print(f"[green]- {acc_id} (Role validated successfully)[/green]")
                                            valid_account_ids.append(acc_id)
                                        else:
                                            console.print(f"[red]- {acc_id} (Unable to assume role - please ensure the role is created)[/red]")
                                
                                if not valid_account_ids:
                                    console.print("[red]No valid child accounts found. Working with the current account only.[/red]")
                                    valid_account_ids = [cloudformation.main_account_id]
                                
                                # Save account IDs to database
                                db_manager = DatabaseManager()
                                db_manager._account_ids = valid_account_ids
                                db_manager.populate_accounts_and_regions()
                                
                                console.print("[green]Deploy completed and account IDs saved![/green]")
                                print(f"\n\n{display.display_bluearch_ascii_art()}")
                            else:
                                console.print(
                                    "[red]The CloudFormation stack creation failed. Stack deletion may be initiated.[/red]"
                                )
                        else:
                            console.print("Deployment aborted.")
                else:
                    # Auto mode
                    org_id = ""  # Initialize org_id with empty string
                    if auto_mode == "yes":
                        org_id = Prompt.ask(
                            "[blue]Enter the AWS Organizational Unit ID where the stack will be deployed[/blue] (optional)",
                            default="",
                            show_default=False,
                        )

                        org_id_pattern = r"^(ou-[a-z0-9]{4,32}-[a-z0-9]{8,32}|r-[a-z0-9]{4,32}|o-[a-z0-9]{10})$"

                        while org_id and not re.match(org_id_pattern, org_id):
                            console.print(
                                "[red]Invalid AWS Organizational Unit ID. It must be in the format 'ou-xxxxxxxx-xxxxxxxx' or 'r-xxxxxxxx'.[/red]"
                            )
                            org_id = Prompt.ask(
                                "[blue]Enter the AWS Organizational Unit ID where the stack will be deployed[/blue] (optional)",
                                default="",
                                show_default=False,
                            )
                        if org_id != "":
                            from aws.wrappers.organizations import Organizations
                            if not Organizations().is_account_delegated_admin_or_management():
                                console.print("[red]You are currently not using a delegated admin or management account. To deploy the stack at the Organization level, please switch to one of those accounts. Alternatively, you can deploy the stack within a single account.[/red]")
                                return
                            else:
                                console.print("[green]You are using a delegated admin or management account. Continuing with the deployment...[/green]")


                    response = cloudformation.deploy_stack(org_id=org_id, workspace=workspace, auto_mode=auto_mode)
                    if response:
                        console.print("Monitoring stack creation...")
                        cloudformation.monitor_stack_creation()

                        if cloudformation.check_stack_status():
                            console.print("[green]Deploy completed![/green]")
                            print(f"\n\n{display.display_bluearch_ascii_art()}")
                        else:
                            console.print(
                                "[red]The CloudFormation stack creation failed. Stack deletion may be initiated.[/red]"
                            )
                    else:
                        console.print("[red]Failed to start stack creation.[/red]")

        except Exception as e:
            error_handler.handle_error(e)
    execute_deploy()
