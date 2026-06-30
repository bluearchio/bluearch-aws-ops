from aws.wrappers.sfn import StateMachine
from utils.logger_config import log
from commons.get import get_accounts_and_regions
from commons.resource_actions import RESOURCE_ACTIONS
from rich.console import Console
from rich.progress import Progress
from pathlib import Path
import os
import platform
import shutil
import tempfile
import json
from rich.prompt import Prompt
import sys
import requests

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


def get_install_dir():
    return f"{Path.home()}/Library/Application Support/bluearch/bin" if sys.platform == "darwin" else f"{Path.home()}/.local/bin"


def update_cli():
    """Update the CLI binary in user space"""
    temp_dir = None
    try:
        # Get installation directory
        install_dir = get_install_dir()
        os.makedirs(install_dir, exist_ok=True)

        # Detect the system architecture
        arch = platform.machine()
        if arch not in ['arm64', 'x86_64']:
            console.print(f"[red]Unsupported architecture: {arch}[/red]")
            return False
        plat = "macos" if sys.platform == "darwin" else "linux"
        env = os.getenv("BLUEARCH_DEBUG")
        binary_url = (
            "https://github.com/bluearchio/bluearch-aws-ops/releases/latest/download/"
            f"bluearch_{plat}_{arch}"
        )

        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        temp_binary = os.path.join(temp_dir, "bluearch.tmp")
        installed_binary = os.path.join(install_dir, "bluearch")
        backup_binary = os.path.join(install_dir, "bluearch.bak")

        # Download with progress bar
        with Progress(console=console, transient=True) as progress:
            download_task = progress.add_task("[green]Downloading BlueArch CLI...", total=None)
            response = requests.get(binary_url, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            progress.update(download_task, total=total_size)
            
            with open(temp_binary, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        progress.update(download_task, advance=len(chunk))

        # Create backup of existing binary if it exists
        if os.path.exists(installed_binary):
            try:
                os.rename(installed_binary, backup_binary)
            except OSError:
                pass  # Ignore if backup creation fails

        # Install new binary with progress bar
        with Progress(console=console, transient=True) as progress:
            install_task = progress.add_task("[green]Installing BlueArch CLI...", total=1)
            
            # Set executable permissions
            os.chmod(temp_binary, 0o755)
            
            # Move to final location
            shutil.move(temp_binary, installed_binary)
            
            progress.update(install_task, advance=1)

        # Remove backup if installation successful
        try:
            if os.path.exists(backup_binary):
                os.remove(backup_binary)
        except OSError:
            pass  # Ignore if backup removal fails
        console.print("[green]BlueArch CLI has been successfully updated[/green]")
        return True

    except requests.exceptions.RequestException as e:
        console.print(f"[red]Error downloading update: {str(e)}[/red]")
        if os.path.exists(backup_binary):
            os.rename(backup_binary, installed_binary)
        return False
    except Exception as e:
        console.print(f"[red]Error during update: {str(e)}[/red]")
        if os.path.exists(backup_binary):
            os.rename(backup_binary, installed_binary)
        return False
    finally:
        # Clean up temporary directory
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
