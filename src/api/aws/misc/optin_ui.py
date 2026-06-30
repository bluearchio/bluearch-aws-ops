import time
from typing import Optional

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from aws.wrappers import opt_in
from aws.misc.alarm_ui import MessageSeverity, _print_message

console = Console()


class OptInUI:
    """Interactive opt-in service management using Rich prompts."""

    def __init__(self):
        self.service_list = opt_in.check_aws_organizations_integrated_services()
        self.current_service: Optional[str] = None
        self.account_statuses: dict = {}
        self.service_cache: dict = {}

    def run(self) -> None:
        """Run the interactive opt-in service management loop."""
        while True:
            console.print()
            self._display_services_table()
            console.print()
            console.print("[dim]Commands: (v)iew accounts, (e)nable/disable service, (q)uit[/dim]")

            action = Prompt.ask(
                "Action",
                choices=["v", "e", "q"],
                default="q",
            )

            if action == "q":
                break
            elif action == "v":
                self._view_accounts()
            elif action == "e":
                self._toggle_service()

    def _display_services_table(self) -> None:
        """Display opt-in services as a Rich table."""
        table = Table(title="Opt-In Services", show_lines=False)
        table.add_column("#", style="dim", width=4)
        table.add_column("Service Name", style="cyan")
        table.add_column("Status", justify="center")

        for idx, (service_name, enabled) in enumerate(self.service_list.items(), 1):
            status_text = "[green]Enabled[/green]" if enabled else "[red]Disabled[/red]"
            table.add_row(str(idx), service_name, status_text)

        console.print(table)

    def _display_accounts_table(self, service_name: str) -> None:
        """Display account statuses for a given service as a Rich table."""
        table = Table(title=f"Accounts for {service_name}", show_lines=False)
        table.add_column("#", style="dim", width=4)
        table.add_column("Account ID", style="cyan", width=40)
        table.add_column("Status", justify="center", width=20)

        for idx, (account_id, status) in enumerate(self.account_statuses.items(), 1):
            status_text = "[green]Enabled[/green]" if status else "[red]Disabled[/red]"
            table.add_row(str(idx), account_id, status_text)

        console.print(table)

    def _select_service_index(self) -> Optional[int]:
        """Prompt user to select a service by number. Returns 0-based index or None."""
        keys = list(self.service_list.keys())
        if not keys:
            _print_message("No services available.", MessageSeverity.WARNING)
            return None

        choice = Prompt.ask(
            f"Select service number [1-{len(keys)}]",
            default="",
        )
        if not choice:
            return None
        if not choice.isdigit() or not (1 <= int(choice) <= len(keys)):
            _print_message("Invalid selection.", MessageSeverity.ERROR)
            return None
        return int(choice) - 1

    def _select_account_index(self) -> Optional[int]:
        """Prompt user to select an account by number. Returns 0-based index or None."""
        keys = list(self.account_statuses.keys())
        if not keys:
            _print_message("No accounts available.", MessageSeverity.WARNING)
            return None

        choice = Prompt.ask(
            f"Select account number [1-{len(keys)}]",
            default="",
        )
        if not choice:
            return None
        if not choice.isdigit() or not (1 <= int(choice) <= len(keys)):
            _print_message("Invalid selection.", MessageSeverity.ERROR)
            return None
        return int(choice) - 1

    def _view_accounts(self) -> None:
        """View accounts for a selected service."""
        idx = self._select_service_index()
        if idx is None:
            return

        service_name = list(self.service_list.keys())[idx]
        if service_name not in ("Compute Optimizer", "Cost Optimization Hub"):
            _print_message(
                f"Account-level view is not available for '{service_name}'.",
                MessageSeverity.INFO,
            )
            return

        self.current_service = service_name

        if service_name in self.service_cache:
            self.account_statuses = self.service_cache[service_name]
        else:
            service_func = {
                "Compute Optimizer": opt_in.compute_optimizer_service_enableness,
                "Cost Optimization Hub": opt_in.cost_optimization_hub_service_enableness,
            }
            self.account_statuses = service_func[service_name]()
            self.service_cache[service_name] = self.account_statuses

        self._run_accounts_loop(service_name)

    def _run_accounts_loop(self, service_name: str) -> None:
        """Run the account-level management loop for a given service."""
        while True:
            console.print()
            self._display_accounts_table(service_name)
            console.print()
            console.print("[dim]Commands: (e)nable/disable account, (b)ack[/dim]")

            action = Prompt.ask(
                "Action",
                choices=["e", "b"],
                default="b",
            )

            if action == "b":
                break
            elif action == "e":
                self._toggle_account()

    def _toggle_service(self) -> None:
        """Toggle a service at the organization level."""
        idx = self._select_service_index()
        if idx is None:
            return

        service_name = list(self.service_list.keys())[idx]
        previous_state = self.service_list[service_name]

        match service_name:
            case "Compute Optimizer":
                service_endpoint = "compute-optimizer.amazonaws.com"
            case "Cost Optimization Hub":
                service_endpoint = "cost-optimization-hub.bcm.amazonaws.com"
            case _:
                _print_message(
                    f"Toggle is not supported for '{service_name}'.",
                    MessageSeverity.INFO,
                )
                return

        action_word = "enable" if not previous_state else "disable"
        if not Confirm.ask(f"Are you sure you want to {action_word} '{service_name}' for the organization?"):
            _print_message("Operation cancelled.", MessageSeverity.INFO)
            return

        status = opt_in.service_trust_status_update(service_endpoint, not previous_state)

        if status:
            self.service_list[service_name] = not previous_state
            _print_message(
                f"Service {action_word}d for the organization.",
                MessageSeverity.SUCCESS,
            )
        else:
            self.service_list[service_name] = previous_state
            _print_message(
                "You are not the management account. "
                "Please try again with the management account.",
                MessageSeverity.ERROR,
            )

    def _toggle_account(self) -> None:
        """Toggle a service at the account level."""
        idx = self._select_account_index()
        if idx is None:
            return

        account_id = list(self.account_statuses.keys())[idx]
        previous_state = self.account_statuses[account_id]

        try:
            status = "Inactive" if previous_state else "Active"

            match self.current_service:
                case "Compute Optimizer":
                    opt_in.compute_optimizer_service_update(
                        optin_organization=False,
                        status=status,
                        accountid=account_id,
                    )
                    success = self._wait_for_account_update(
                        opt_in.compute_optimizer_service_enableness,
                        account_id,
                        previous_state,
                        status,
                    )
                case "Cost Optimization Hub":
                    opt_in.cost_optimization_hub_service_update(
                        optin_organization=False,
                        status=status,
                        accountid=account_id,
                    )
                    success = self._wait_for_account_update(
                        opt_in.cost_optimization_hub_service_enableness,
                        account_id,
                        previous_state,
                        status,
                    )
                case _:
                    _print_message("Unsupported service.", MessageSeverity.ERROR)
                    return

            if not success:
                _print_message(
                    f"Error updating {self.current_service} service for account {account_id}.",
                    MessageSeverity.ERROR,
                )
        except Exception as e:
            _print_message(
                f"Error updating {self.current_service} service for account {account_id}: {e}",
                MessageSeverity.ERROR,
            )

    def _wait_for_account_update(
        self,
        service_function,
        account_id: str,
        previous_state: bool,
        status: str,
    ) -> bool:
        """Poll until the account status update is confirmed (up to 5 retries)."""
        for _ in range(5):
            statuses = service_function()
            expected_value = status == "Active"
            if statuses[account_id] == expected_value:
                self.account_statuses[account_id] = not previous_state
                _print_message(
                    f"Account {account_id} has been "
                    f"{'enabled' if not previous_state else 'disabled'} "
                    f"for {self.current_service} service.",
                    MessageSeverity.SUCCESS,
                )
                return True
            time.sleep(2)

        self.account_statuses[account_id] = previous_state
        return False
