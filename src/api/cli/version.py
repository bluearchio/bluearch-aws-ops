import os
import re

from typer import Exit
from rich.console import Console

from aws.misc.version_controller import CURRENT_VERSION


def version_callback(value: bool):
    if value:
        console = Console()
        console.print(f"BlueArch CLI version: [blue]{CURRENT_VERSION}[/blue]")
        skip_update_check = os.environ.get("BLUEARCH_SKIP_UPDATE_CHECK", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if (
            skip_update_check
            or os.environ.get("BLUEARCH_CORE_VERSION_PROBE")
            or _is_development_version(CURRENT_VERSION)
        ):
            raise Exit()
        try:
            from aws.misc.version_controller import get_updates
            from aws.misc.display import display_updates
            updates = get_updates()
            if updates is not None:
                if updates:
                    display_updates(updates)
                    console.print("[green]Type [bold blue]bluearch update[/bold blue] to update.[/green]")
                else:
                    console.print("BlueArch CLI: [green]up to date![/green]")
            else:
                console.print("BlueArch CLI: [yellow]Unable to check for updates at this time.[/yellow]")
        except UnicodeDecodeError:
            console.print("[yellow]Warning: Encountered encoding issues while checking for updates.[/yellow]")
        except Exception as e:
            console.print(f"BlueArch CLI: [red]Error checking for updates: {str(e)}[/red]")
        raise Exit()


def _is_development_version(version: str) -> bool:
    value = str(version or "").strip()
    return value.upper() in {"LOCAL", "DEVELOPMENT"} or bool(re.fullmatch(r"[0-9a-f]{7,40}", value, re.IGNORECASE))
