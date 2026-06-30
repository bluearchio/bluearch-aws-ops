"""Display utilities with emoji output — shared patterns for all CLI commands.

Both the BlueArch CLI and Tag Manager CLI will use emoji-based output.
These helpers ensure consistent formatting across all commands.
"""

import sys
import locale

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# ---------------------------------------------------------------------------
# UTF-8 setup (run at import time)
# ---------------------------------------------------------------------------

def _ensure_utf8():
    """Ensure stdout can handle emoji output."""
    try:
        locale.setlocale(locale.LC_ALL, "C.UTF-8")
    except locale.Error:
        try:
            locale.setlocale(locale.LC_ALL, "en_US.UTF-8")
        except locale.Error:
            pass

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

_ensure_utf8()


# ---------------------------------------------------------------------------
# Console singleton
# ---------------------------------------------------------------------------

console = Console()


# ---------------------------------------------------------------------------
# Print helpers with emoji prefixes
# ---------------------------------------------------------------------------

def print_safe(message: str, **kwargs):
    """Print a message to the console (Rich-formatted)."""
    console.print(message, **kwargs)


def print_success(message: str):
    """Print a success message with green checkmark."""
    console.print(f"[green]>> {message}[/green]")


def print_error(message: str):
    """Print an error message with red cross."""
    console.print(f"[red]>> {message}[/red]")


def print_warning(message: str):
    """Print a warning message with yellow warning sign."""
    console.print(f"[yellow]>> {message}[/yellow]")


def print_info(message: str):
    """Print an info message with blue info sign."""
    console.print(f"[cyan]>> {message}[/cyan]")


# ---------------------------------------------------------------------------
# Structured output helpers
# ---------------------------------------------------------------------------

def print_header(title: str):
    """Print a bold section header."""
    console.print()
    console.print(f"[bold]{title}[/bold]")
    console.print()


def print_key_value(key: str, value, key_style: str = "bold", value_style: str = "cyan"):
    """Print a key-value pair."""
    console.print(f"  [{key_style}]{key}:[/{key_style}] [{value_style}]{value}[/{value_style}]")


def print_panel(title: str, content: str, style: str = "blue"):
    """Print content in a Rich panel."""
    console.print(Panel(content, title=title, border_style=style))


def create_table(title: str = "", **kwargs) -> Table:
    """Create a styled Rich table matching BlueArch conventions."""
    return Table(
        title=title,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        **kwargs,
    )
