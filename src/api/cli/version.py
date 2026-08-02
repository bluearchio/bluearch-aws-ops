import re

from typer import Exit
from rich.console import Console

from aws.misc.version_controller import CURRENT_VERSION


PUBLIC_OPS_EXECUTABLE = "bluearch-aws-ops"
CORE_FORMULA = "bluearchio/tap/bluearch-aws-core"
OPS_FORMULA = "bluearchio/tap/bluearch-aws-ops"


def version_callback(value: bool):
    if value:
        console = Console()
        console.print(f"{PUBLIC_OPS_EXECUTABLE} [blue]{CURRENT_VERSION}[/blue]")
        if not _is_development_version(CURRENT_VERSION):
            console.print("Check for updates with:")
            console.print(f"  [cyan]brew trust --formula {CORE_FORMULA}[/cyan]")
            console.print(f"  [cyan]brew trust --formula {OPS_FORMULA}[/cyan]")
            console.print(f"  [cyan]brew update && brew outdated {OPS_FORMULA}[/cyan]")
        raise Exit()


def _is_development_version(version: str) -> bool:
    value = str(version or "").strip()
    return value.upper() in {"LOCAL", "DEVELOPMENT"} or bool(re.fullmatch(r"[0-9a-f]{7,40}", value, re.IGNORECASE))
