import traceback
from utils.logger_config import log
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from botocore.exceptions import NoCredentialsError, ClientError, NoRegionError
from commons import execution
import sys

# Ensure console can handle UTF-8 characters
sys.stdout.reconfigure(encoding='utf-8')

class ErrorHandler:
    def __init__(self):
        self.console = Console()
        self.credentials_error_handled = False

    def handle_error(self, error):
        error_handlers = {
            NoCredentialsError: self._handle_no_credentials_error,
            ClientError: self._handle_client_error,
            NoRegionError: self._handle_no_region_error,
        }
        
        if isinstance(error, AttributeError) and "PynamoDB Models must have a table_name" in str(error):
            self._handle_dynamodb_table_not_found()
        else:
            handler = error_handlers.get(type(error), self._handle_generic_error)
            handler(error)
        log.debug(traceback.format_exc())

    def handle_update_error(self, error, cloudformation=None):
        if isinstance(error, PermissionError):
            self.console.print(str(error))
        elif isinstance(error, NoCredentialsError):
            self._handle_no_credentials_error()
        elif isinstance(error, NoRegionError):
            self._handle_no_region_error()
        elif cloudformation:
            execution.handle_update_error(cloudformation, error)
        else:
            self._handle_generic_error(error)
        log.debug(traceback.format_exc())

    def _handle_dynamodb_table_not_found(self):
        self.console.print("[yellow]DynamoDB table not found.[/yellow]")
        self.console.print("[yellow]Please make sure you have the AWS credentials set up correctly and the application deployed.[/yellow]")
        self._handle_no_credentials_error()
        self._handle_missing_cloudformation_stack()

    def _handle_no_credentials_error(self, error=None):
        if not self.credentials_error_handled:
            message, table, message_panel = self._get_no_credentials_error_message()
            self.console.print(message, table, message_panel)
            self.credentials_error_handled = True

    def _handle_client_error(self, error):
        error_code = error.response['Error'].get('Code')
        error_message = error.response['Error'].get('Message', '')

        if error_code == 'AccessDenied':
            if "arn:aws:iam::None:role/None" not in error_message:
                self._handle_no_credentials_error()
            else:
                self.console.print("[red]Access denied[/red]")
                self._handle_missing_cloudformation_stack()
        elif error_code in ['InvalidClientTokenId', 'ExpiredTokenException']:
            self.console.print(f"[red]{'Invalid AWS Token Id' if error_code == 'InvalidClientTokenId' else 'AWS Token Expired'}[/red]")
            self._handle_no_credentials_error()
        else:
            self.console.print(f"[red]An AWS client error occurred: {str(error)}[/red]")

    def _handle_no_region_error(self, error=None):
        self.console.print("[red]No region was specified.[/red]")
        self.console.print("[red]Please set the AWS_DEFAULT_REGION environment variable with us-east-1 region.[/red]")
        self.console.print("[red]For example: export AWS_DEFAULT_REGION=us-east-1[/red]")

    def _handle_generic_error(self, error):
        self.console.print(f"[red]An error occurred: {str(error)}[/red]")

    def _handle_missing_cloudformation_stack(self):
        self.console.print(
            "[yellow]CloudFormation stack not found. Configure cross-account infrastructure with:[/yellow] "
            "[bold blue]bluearch-aws-ops setup multi-account --complete[/bold blue]"
        )

    def _get_no_credentials_error_message(self):
        message = Text("Please set up your AWS access using one of the following methods:", style="bold red")
        table = self._create_credentials_table()
        message_panel = self._create_next_steps_panel()
        return message, table, message_panel

    def _create_credentials_table(self):
        table = Table(title="AWS Credential Setup Options", show_header=True, header_style="bold magenta", expand=True)
        table.add_column("Method", style="cyan", no_wrap=True, ratio=1)
        table.add_column("Steps", style="green", ratio=3)

        table.add_row(
            "1. AWS Identity Center (SSO)\n[bold yellow]Recommended[/bold yellow]",
            "a. [bold]aws configure sso --profile your_sso_profile_name[/bold]\n"
            "b. [bold]aws sso login --profile your_sso_profile_name[/bold]\n"
            "c. [bold]export AWS_PROFILE=your_sso_profile_name[/bold]"
        )

        table.add_section()

        table.add_row(
            "2. AWS Access Keys",
            "Choose one:\n"
            "a. Run [bold]aws configure[/bold] and follow the prompts\n"
            "b. Set environment variables:\n"
            "   [bold]export AWS_ACCESS_KEY_ID=your_access_key_id[/bold]\n"
            "   [bold]export AWS_SECRET_ACCESS_KEY=your_secret_access_key[/bold]\n"
            "   [bold]export AWS_DEFAULT_REGION=us-east-1[/bold] [yellow](Always use us-east-1)[/yellow]\n"
            "   [bold]export AWS_SESSION_TOKEN=your_session_token[/bold] (if applicable)\n"
            "c. Use an existing AWS profile:\n"
            "   [bold]export AWS_PROFILE=your_profile_name[/bold]"
        )

        return table

    def _create_next_steps_panel(self):
        return Panel(
            Text.from_markup(
                "After setting up your AWS access, please try your command again.",
                style="italic"
            ),
            title="Next Steps",
            border_style="blue"
        )

    def handle_dynamodb_error(self, error):
        error_message = str(error.cause)
        if "Unable to locate credentials" in error_message:
            self._handle_no_credentials_error()
        elif "Requested resource not found" in error_message:
            self.console.print(
                "[red]Requested resource not found. Refresh local data with [/red]"
                "[bold blue]'bluearch-aws-ops scan'[/bold blue]"
            )
        else:
            self.console.print(f"[red]Unexpected error: {error_message}[/red]")
        log.debug(traceback.format_exc())
    def handle_scheduler_error(self, error):
        if "Parameter validation failed" in error:
            self._handle_no_credentials_error()
        elif isinstance(error, ClientError):
            self._handle_client_error(error)
        else:
            self.console.print(f"[red]An error occurred while setting the scheduler: {error}[/red]")
        log.debug(traceback.format_exc())
error_handler = ErrorHandler()
