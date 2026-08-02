from enum import Enum
from typing import Optional

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.progress import Progress
from rich.table import Table

from commons import get
from aws.wrappers.cloudwatch import CloudWatchWrapper
from aws.wrappers.sns import SnsWrapper
from aws.wrappers.slack_webhook import SlackWebhookWrapper

console = Console()


class MessageSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


_SEVERITY_STYLES = {
    MessageSeverity.INFO: "blue",
    MessageSeverity.WARNING: "yellow",
    MessageSeverity.ERROR: "red",
    MessageSeverity.SUCCESS: "green",
}


def _print_message(message: str, severity: MessageSeverity = MessageSeverity.INFO) -> None:
    """Print a styled message to the console."""
    color = _SEVERITY_STYLES.get(severity, "blue")
    console.print(f"[{color}]{message}[/{color}]")


def _display_alarm_table(alarm_config: dict) -> None:
    """Display alarm configuration as a Rich table."""
    table = Table(title="Alarm Configuration", show_lines=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Recommendation Type", style="cyan")
    table.add_column("Alarm Enabled", justify="center")
    table.add_column("Alarm Threshold", justify="center")

    for idx, (rec_type, config) in enumerate(alarm_config.items(), 1):
        enabled_text = "[green]Yes[/green]" if config["enabled"] else "[red]No[/red]"
        table.add_row(str(idx), rec_type, enabled_text, str(config["threshold"]))

    console.print(table)


def _display_target_table(target_config: dict) -> None:
    """Display notification targets as a Rich table."""
    table = Table(title="Notification Targets", show_lines=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Endpoint Type", style="cyan")
    table.add_column("Endpoint Value")
    table.add_column("Confirmed", justify="center")

    for idx, (endpoint, config) in enumerate(target_config.items(), 1):
        display_value = mask_webhook_url(endpoint) if config["type"] == "Slack" else endpoint
        confirmed_text = "[green]Yes[/green]" if config["confirmed"] else "[yellow]No[/yellow]"
        table.add_row(str(idx), config["type"], display_value, confirmed_text)

    console.print(table)


class AlarmConfigUI:
    """Interactive alarm configuration using Rich prompts instead of Textual TUI."""

    def __init__(self, cloudwatch: CloudWatchWrapper):
        self.cloudwatch = cloudwatch
        self.alarm_config = self._get_alarm_config()

    def _get_alarm_config(self) -> dict:
        from commons.resource_actions import RESOURCE_ACTIONS
        recommendation_types = [action.lower() for actions in RESOURCE_ACTIONS.values() for action in actions]
        config = {}
        alarms = self.cloudwatch.get_alarms()

        for rec_type in recommendation_types:
            config[rec_type] = {
                "enabled": False,
                "threshold": 1,
            }

        for alarm in alarms:
            alarm_name = alarm["AlarmName"]
            for rec_type in recommendation_types:
                if rec_type in alarm_name:
                    config[rec_type] = {
                        "enabled": alarm["ActionsEnabled"],
                        "threshold": int(alarm["Threshold"]),
                    }
                    break
        return config

    def run(self) -> None:
        """Run the interactive alarm configuration loop."""
        while True:
            console.print()
            _display_alarm_table(self.alarm_config)
            console.print()
            console.print("[dim]Commands: (t)oggle enabled, (e)dit threshold, (d)one[/dim]")

            action = Prompt.ask(
                "Action",
                choices=["t", "e", "d"],
                default="d",
            )

            if action == "d":
                break
            elif action == "t":
                self._toggle_enabled()
            elif action == "e":
                self._edit_threshold()

    def _select_alarm_index(self) -> Optional[int]:
        """Prompt user to select an alarm by number. Returns 0-based index or None."""
        keys = list(self.alarm_config.keys())
        if not keys:
            _print_message("No alarm types available.", MessageSeverity.WARNING)
            return None

        choice = Prompt.ask(
            f"Select alarm number [1-{len(keys)}]",
            default="",
        )
        if not choice:
            return None
        if not choice.isdigit() or not (1 <= int(choice) <= len(keys)):
            _print_message("Invalid selection.", MessageSeverity.ERROR)
            return None
        return int(choice) - 1

    def _toggle_enabled(self) -> None:
        """Toggle the enabled state of a selected alarm."""
        idx = self._select_alarm_index()
        if idx is None:
            return
        rec_type = list(self.alarm_config.keys())[idx]
        self.alarm_config[rec_type]["enabled"] = not self.alarm_config[rec_type]["enabled"]
        new_state = "enabled" if self.alarm_config[rec_type]["enabled"] else "disabled"
        _print_message(f"Alarm for '{rec_type}' is now {new_state}.", MessageSeverity.SUCCESS)

    def _edit_threshold(self) -> None:
        """Edit the threshold of a selected alarm."""
        idx = self._select_alarm_index()
        if idx is None:
            return
        rec_type = list(self.alarm_config.keys())[idx]
        current = self.alarm_config[rec_type]["threshold"]

        value = Prompt.ask(
            f"Enter new threshold for '{rec_type}' (1-999)",
            default=str(current),
        )
        if value.isdigit() and 1 <= int(value) <= 999:
            self.alarm_config[rec_type]["threshold"] = int(value)
            _print_message(f"Threshold for '{rec_type}' set to {value}.", MessageSeverity.SUCCESS)
        else:
            _print_message("Invalid input. Please enter a number between 1 and 999.", MessageSeverity.ERROR)


class AlarmTargetUI:
    """Interactive notification target management using Rich prompts."""

    def __init__(self, sns: SnsWrapper, slack: SlackWebhookWrapper):
        self.sns = sns
        self.slack = slack
        self.target_config = self._get_target_config()

    def _get_target_config(self) -> dict:
        config = {}
        subscriptions = self.sns.list_subscriptions()
        for sub in subscriptions:
            if sub["Protocol"] == "email":
                config[sub["Endpoint"]] = {
                    "type": "Email",
                    "confirmed": sub["SubscriptionArn"] != "PendingConfirmation",
                }

        slack_webhooks = self.slack.list_webhooks()
        for webhook in slack_webhooks:
            config[webhook] = {"type": "Slack", "confirmed": True}

        return config

    def run(self) -> None:
        """Run the interactive target management loop."""
        if not self.target_config:
            _print_message("No notification targets are currently configured.", MessageSeverity.WARNING)

        while True:
            console.print()
            _display_target_table(self.target_config)
            console.print()
            console.print("[dim]Commands: (a)dd, (d)elete, (e)dit, (t)est Slack, (q)uit[/dim]")

            action = Prompt.ask(
                "Action",
                choices=["a", "d", "e", "t", "q"],
                default="q",
            )

            if action == "q":
                break
            elif action == "a":
                self._add_endpoint()
            elif action == "d":
                self._delete_endpoint()
            elif action == "e":
                self._edit_endpoint()
            elif action == "t":
                self._test_endpoint()

    def _select_endpoint_index(self) -> Optional[int]:
        """Prompt user to select an endpoint by number. Returns 0-based index or None."""
        keys = list(self.target_config.keys())
        if not keys:
            _print_message("No endpoints configured.", MessageSeverity.WARNING)
            return None

        choice = Prompt.ask(
            f"Select endpoint number [1-{len(keys)}]",
            default="",
        )
        if not choice:
            return None
        if not choice.isdigit() or not (1 <= int(choice) <= len(keys)):
            _print_message("Invalid selection.", MessageSeverity.ERROR)
            return None
        return int(choice) - 1

    def _add_endpoint(self) -> None:
        """Add a new notification endpoint (Email or Slack)."""
        endpoint_type = Prompt.ask(
            "Select endpoint type",
            choices=["Email", "Slack"],
            default="Email",
        )

        if endpoint_type == "Email":
            value = Prompt.ask("Enter email address")
            if not value:
                _print_message("Email subscription creation cancelled.", MessageSeverity.INFO)
                return
            subscription_arn = self.sns.create_subscription("email", value)
            if subscription_arn:
                confirmed = subscription_arn != "PendingConfirmation"
                if value in self.target_config:
                    _print_message("An endpoint with this email already exists.", MessageSeverity.WARNING)
                    return
                self.target_config[value] = {"type": "Email", "confirmed": confirmed}
                _print_message(
                    "Email subscription created. Please check your email to confirm the subscription.",
                    MessageSeverity.SUCCESS,
                )
            else:
                _print_message("Failed to create email subscription.", MessageSeverity.ERROR)

        elif endpoint_type == "Slack":
            value = Prompt.ask("Enter Slack webhook URL")
            if not value:
                _print_message("Webhook addition cancelled.", MessageSeverity.INFO)
                return
            success, message = self.slack.create_webhook(value)
            if success:
                if value in self.target_config:
                    _print_message("A webhook with this URL already exists.", MessageSeverity.WARNING)
                    return
                self.target_config[value] = {"type": "Slack", "confirmed": True}
                _print_message(message, MessageSeverity.SUCCESS)
            else:
                _print_message(f"Failed to add Slack webhook: {message}", MessageSeverity.ERROR)

    def _delete_endpoint(self) -> None:
        """Delete a notification endpoint."""
        idx = self._select_endpoint_index()
        if idx is None:
            return

        endpoint = list(self.target_config.keys())[idx]
        config = self.target_config[endpoint]
        endpoint_type = config["type"]

        if not Confirm.ask(f"Delete {endpoint_type} endpoint?"):
            _print_message("Delete cancelled.", MessageSeverity.INFO)
            return

        if endpoint_type == "Email":
            if not config["confirmed"]:
                _print_message(
                    "SNS will automatically delete this pending subscription after 3 days.",
                    MessageSeverity.INFO,
                )
                return
            delete_result = self.sns.delete_subscription(endpoint)
            if delete_result != "deleted":
                _print_message(f"Failed to delete email subscription: {delete_result}", MessageSeverity.ERROR)
                return
        elif endpoint_type == "Slack":
            if not self.slack.delete_webhook(endpoint):
                _print_message("Failed to delete Slack webhook.", MessageSeverity.ERROR)
                return

        del self.target_config[endpoint]
        _print_message(f"{endpoint_type} endpoint deleted successfully.", MessageSeverity.SUCCESS)

    def _edit_endpoint(self) -> None:
        """Edit an existing notification endpoint."""
        idx = self._select_endpoint_index()
        if idx is None:
            return

        old_endpoint = list(self.target_config.keys())[idx]
        config = self.target_config[old_endpoint]
        endpoint_type = config["type"]

        if endpoint_type == "Email":
            if not config["confirmed"]:
                _print_message(
                    "SNS will automatically delete this pending subscription after 3 days. "
                    "You can add a new subscription instead.",
                    MessageSeverity.INFO,
                )
                return
            new_value = Prompt.ask("Enter new email address", default=old_endpoint)
            if not new_value or new_value == old_endpoint:
                _print_message("Edit operation cancelled.", MessageSeverity.INFO)
                return
            self.sns.delete_subscription(old_endpoint)
            subscription_arn = self.sns.create_subscription("email", new_value)
            if subscription_arn:
                confirmed = subscription_arn != "PendingConfirmation"
                del self.target_config[old_endpoint]
                self.target_config[new_value] = {"type": "Email", "confirmed": confirmed}
                _print_message("Email endpoint updated successfully.", MessageSeverity.SUCCESS)
            else:
                _print_message("Failed to update email endpoint.", MessageSeverity.ERROR)

        elif endpoint_type == "Slack":
            new_value = Prompt.ask("Enter new Slack webhook URL")
            if not new_value:
                _print_message("Edit operation cancelled.", MessageSeverity.INFO)
                return
            success = self.slack.delete_webhook(old_endpoint)
            if success:
                success, message = self.slack.create_webhook(new_value)
                if success:
                    del self.target_config[old_endpoint]
                    self.target_config[new_value] = {"type": "Slack", "confirmed": True}
                    _print_message(message, MessageSeverity.SUCCESS)
                else:
                    _print_message(f"Failed to update Slack webhook: {message}", MessageSeverity.ERROR)
            else:
                _print_message("Failed to delete old Slack webhook.", MessageSeverity.ERROR)

    def _test_endpoint(self) -> None:
        """Send a test message to a Slack webhook endpoint."""
        idx = self._select_endpoint_index()
        if idx is None:
            return

        endpoint = list(self.target_config.keys())[idx]
        config = self.target_config[endpoint]

        if config["type"] != "Slack":
            _print_message("Test action is only available for Slack webhooks.", MessageSeverity.INFO)
            return

        if self.slack.test_webhook(endpoint):
            _print_message("Test message sent successfully.", MessageSeverity.SUCCESS)
        else:
            _print_message("Failed to send test message.", MessageSeverity.ERROR)


def configure_alarms():
    """Configure CloudWatch alarms for recommendation types."""
    try:
        recommendation_types = get.get_recommendation_types()
        if not recommendation_types:
            console.print(
                "[yellow]Not possible to create alarms because no recommendation type was found. "
                "This usually means the populate command hasn't been run yet.[/yellow]"
            )
            if Prompt.ask(
                "[blue]Would you like to run the populate command now?[/blue]",
                choices=["yes", "no"],
                default="yes",
            ) == "yes":
                from cli.recommendations import populate
                populate()
                recommendation_types = get.get_recommendation_types()
            else:
                console.print(
                    "[yellow]Aborting alarm configuration. "
                    "Please run 'bluearch-aws-ops scan' before configuring alarms.[/yellow]"
                )

        cloudwatch = CloudWatchWrapper()
        ui = AlarmConfigUI(cloudwatch)
        ui.run()

        if Prompt.ask(
            "\n[blue]Do you want to save this alarm configuration?[/blue]",
            choices=["yes", "no"],
            default="no",
        ) == "yes":
            changes_made = False
            total_alarms = len(ui.alarm_config)
            with Progress(console=console, transient=True) as progress:
                task = progress.add_task("[green]Creating / updating alarms...", total=total_alarms)

                for rec_type, config in ui.alarm_config.items():
                    cloudwatch.create_alarm(
                        alarm_name=f"bluearch_{rec_type}_alarm",
                        alarm_enabled=config["enabled"],
                        alarm_threshold=config["threshold"],
                    )
                    progress.advance(task)
                    changes_made = True

            if changes_made:
                console.print("[green]CloudWatch alarms created/updated.[/green]")
            else:
                console.print("[yellow]No changes were made to the alarm configuration.[/yellow]")

            # Check if there are any notification targets configured
            sns = SnsWrapper()
            slack = SlackWebhookWrapper()

            sns_subscriptions = sns.list_subscriptions()
            slack_webhooks = slack.list_webhooks()

            if not sns_subscriptions and not slack_webhooks:
                console.print("[yellow]No notification targets (email or Slack) are currently configured.[/yellow]")
                if Prompt.ask(
                    "[blue]Would you like to configure notification targets now?[/blue]",
                    choices=["yes", "no"],
                    default="yes",
                ) == "yes":
                    configure_targets()
        else:
            console.print("[yellow]Alarm configuration not saved.[/yellow]")
        return True
    except Exception as e:
        return False


def configure_targets():
    """Configure notification targets (Email and Slack)."""
    try:
        sns = SnsWrapper()
        slack = SlackWebhookWrapper()

        # Get current configuration
        current_config = {}
        current_subscriptions = sns.list_subscriptions()
        for sub in current_subscriptions:
            if sub["Protocol"] == "email":
                current_config[sub["Endpoint"]] = {
                    "type": "Email",
                    "confirmed": sub["SubscriptionArn"] != "PendingConfirmation",
                }

        current_webhooks = slack.list_webhooks()
        for webhook in current_webhooks:
            current_config[webhook] = {"type": "Slack", "confirmed": True}

        # Run the UI
        ui = AlarmTargetUI(sns, slack)
        ui.run()

        if Prompt.ask(
            "\n[blue]Do you want to save this notification target configuration?[/blue]",
            choices=["yes", "no"],
            default="no",
        ) == "yes":
            changes_made = False
            # Compare and process changes
            for endpoint, config in ui.target_config.items():
                if endpoint not in current_config:
                    # New endpoint
                    if config["type"] == "Email":
                        sns.create_subscription("email", endpoint)
                        console.print(f"[green]New email subscription created for {endpoint}[/green]")
                        changes_made = True
                    elif config["type"] == "Slack":
                        success, message = slack.create_webhook(endpoint)
                        if success:
                            console.print(f"[green]{message} for {endpoint}[/green]")
                            changes_made = True
                        else:
                            console.print(f"[red]Failed to configure Slack webhook {endpoint}: {message}[/red]")
                elif current_config[endpoint] != config:
                    # Updated endpoint
                    if config["type"] == "Email":
                        sns.delete_subscription(endpoint)
                        sns.create_subscription("email", endpoint)
                        console.print(f"[green]Email subscription updated for {endpoint}[/green]")
                        changes_made = True
                    elif config["type"] == "Slack":
                        success, message = slack.create_webhook(endpoint)
                        if success:
                            console.print(f"[green]Slack webhook updated for {endpoint}[/green]")
                            changes_made = True
                        else:
                            console.print(f"[red]Failed to update Slack webhook {endpoint}: {message}[/red]")

            # Process deletions
            for endpoint in current_config:
                if endpoint not in ui.target_config:
                    if current_config[endpoint]["type"] == "Email":
                        result = sns.delete_subscription(endpoint)
                        if result == "deleted":
                            console.print(f"[green]Email subscription deleted for {endpoint}[/green]")
                            changes_made = True
                        elif result == "pending":
                            console.print(
                                f"[yellow]Pending email subscription for {endpoint} has been removed[/yellow]"
                            )
                            changes_made = True
                    elif current_config[endpoint]["type"] == "Slack":
                        if slack.delete_webhook(endpoint):
                            console.print(f"[green]Slack webhook deleted for {endpoint}[/green]")
                            changes_made = True

            if changes_made:
                console.print("[green]Notification targets configuration updated.[/green]")
                console.print(
                    "[blue]Please check your email for any new subscription confirmation messages.[/blue]"
                )
            else:
                console.print("[yellow]No changes were made to the notification target configuration.[/yellow]")
        else:
            console.print("[yellow]Notification target configuration not saved.[/yellow]")
        return True
    except Exception as e:
        return False


def mask_webhook_url(url: str) -> str:
    if url is None:
        return ""
    parts = url.split("/")
    if len(parts) >= 5:
        masked_part = f"{parts[0]}//{parts[2]}/{parts[3][:3]}...{parts[4][-4:]}"
        return masked_part
    return "..." + url[-10:]  # Fallback if URL format is unexpected
