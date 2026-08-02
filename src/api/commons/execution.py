from aws.wrappers.sfn import StateMachine
from utils.logger_config import log
from commons.get import get_accounts_and_regions
from commons.resource_actions import RESOURCE_ACTIONS
from rich.console import Console
from rich.prompt import Prompt
import sys

# Ensure console can handle UTF-8 characters
sys.stdout.reconfigure(encoding='utf-8')

console = Console()
def populate():
    try:
        accounts_list = list(get_accounts_and_regions().keys())
        state_machine = StateMachine()
        resources = list(RESOURCE_ACTIONS.keys())

        log.debug(f"Starting state machine executions for accounts: {accounts_list} and resources: {resources}")
        state_machine.populate(accounts_list, resources)
    except Exception as e:
        from aws.misc.error_handlings import error_handler
        error_handler.handle_error(e)
        raise

def confirm_update():
    # return confirm("Are you sure you want to update the BlueArch CLI + CloudFormation stack?", abort=True)
    return Prompt.ask("[blue]Are you sure you want to update the BlueArch CLI + CloudFormation stack?[/blue]", choices=["yes", "no"], default="no") == "yes"

def confirm_update_with_changes():
    # return confirm("Do you want to proceed with the update?", abort=True)
    return Prompt.ask("[blue]Do you want to proceed with the update?[/blue]", choices=["yes", "no"], default="no") == "yes"
def handle_no_updates(cloudformation):
    console.print("[yellow]Bluearch Cloudformation Stack not updated: No changes has been detected.[/yellow]")
    cloudformation.delete_change_set()

def handle_update_aborted(cloudformation):
    console.print("Update aborted.")
    cloudformation.delete_change_set()

def handle_update_error(cloudformation, e):
    console.print(f"[red]Error occurred during the update process: {e}[/red]")
    cloudformation.delete_change_set()

def execute_update(cloudformation, change_set):
    cloudformation.execute_change_set()
    cloudformation.monitor_stack_update(change_set)
    # console.print("Waiting for the update to complete...")
    update_status = cloudformation.wait_for_change_set()

    if update_status == "UPDATE_COMPLETE":
        console.print("[green]BlueArch CLI + CloudFormation stack were updated successfully.[/green]")
    else:
        console.print(f"[red]The update has failed for the following reason: {update_status}[/red]")
