"""Web dashboard CLI commands — start, stop, status with daemon support.

Usage:
    bluearch-aws-core start --daemon
    bluearch-aws-ops web stop
    bluearch-aws-ops web status
"""

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Optional

import typer
from rich.console import Console

console = Console()

# PID file for daemon management
PID_DIR = os.path.join(os.path.expanduser("~"), ".bluearch")
PID_FILE = os.path.join(PID_DIR, "web-server.pid")
LOG_DIR = os.path.join(PID_DIR, "logs")
MANAGED_DASHBOARD_PORTS = (8095, 8096)
APP_PROCESS_MARKERS = (
    "bluearch.py",
    "bluearch-aws-ops web start",
    "web.app:create_app",
    "tag_manager_cli",
    "tag-manager web start",
)
LEGACY_OPS_PROCESS_MARKERS = ("bluearch web start",)
PUBLIC_OPS_EXECUTABLE = "bluearch-aws-ops"


class _DefaultStartGroup(typer.core.TyperGroup):
    """Routes direct options to the hidden Core-managed start command."""

    def parse_args(self, ctx, args):
        if args and args[0].startswith("-") and args[0] not in ("-h", "--help"):
            args = ["start"] + list(args)
        return super().parse_args(ctx, args)


web_app = typer.Typer(
    cls=_DefaultStartGroup,
    help=(
        "[bold]Web Dashboard[/bold] -- browser-based UI for BlueArch CLI.\n\n"
        "[green]Quick Start:[/green]\n"
        "  bluearch-aws-core start --daemon  Start core and available web dashboards\n"
        "  bluearch-aws-ops web stop         Stop the BlueArch dashboard\n"
    ),
    no_args_is_help=False,
    rich_markup_mode="rich",
)


@web_app.callback(invoke_without_command=True)
def web_help(ctx: typer.Context):
    """Web Dashboard - Browser-based UI for BlueArch CLI"""
    if ctx.invoked_subcommand is None:
        console.print()
        console.print("[bold]Web Dashboard[/bold] - Browser-based UI for BlueArch CLI")
        console.print()
        console.print("[bold cyan]SERVER:[/bold cyan]")
        console.print("  Managed by bluearch-aws-core")
        console.print("  stop           Stop the running server")
        console.print("  status         Show server status")
        console.print()
        console.print("[bold cyan]QUICK START:[/bold cyan]")
        console.print("  1. bluearch-aws-core start --daemon     # Start core and available web dashboards")
        console.print("  2. Open http://localhost:8095 in your browser")
        console.print()
        console.print("[dim]The dashboard is local-only and uses the bluearch-aws-core service token.[/dim]")
        console.print()


@web_app.command(hidden=True)
def start(
    port: int = typer.Option(8095, "--port", "-p", help="Server port"),
    host: str = typer.Option("127.0.0.1", "--host", help="Server host"),
    daemon: bool = typer.Option(False, "--daemon", "-d", help="Run in background"),
    log_level: str = typer.Option("info", "--log-level", "-l", help="Log level: debug, info, warning, error"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not auto-open browser"),
):
    """Start the web dashboard server."""
    _ensure_core_managed_start()
    daemon_child = os.environ.get("BLUEARCH_WEB_DAEMON_CHILD") == "1"
    _ensure_core_dependency()

    # Override from env var if set
    log_level = os.environ.get("BLUEARCH_WEB_LOG_LEVEL", log_level).lower()
    if log_level not in ("debug", "info", "warning", "error"):
        log_level = "info"

    if not daemon_child and _is_server_running():
        if port in MANAGED_DASHBOARD_PORTS:
            console.print("[yellow]Existing BlueArch web server detected; restarting fixed SSO ports.[/yellow]")
        else:
            console.print("[yellow]Server is already running.[/yellow]")
            _show_status()
            return

    port = _resolve_start_port(host, port)

    if daemon:
        _start_daemon(host, port, log_level, no_browser)
    else:
        _start_foreground(host, port, log_level, no_browser)


@web_app.command()
def stop():
    """Stop the web dashboard server."""
    pid = _read_pid()
    if pid is None:
        console.print("[yellow]No running server found.[/yellow]")
        return

    console.print(f"Stopping server (PID {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        console.print("[yellow]Process already gone.[/yellow]")
        _remove_pid()
        return

    # Wait for graceful shutdown
    for _ in range(50):
        try:
            os.kill(pid, 0)
            time.sleep(0.1)
        except ProcessLookupError:
            break
    else:
        console.print("[yellow]Force killing...[/yellow]")
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    _remove_pid()
    console.print("[green]Server stopped.[/green]")


@web_app.command()
def status():
    """Show web dashboard server status."""
    _show_status()


# ---------------------------------------------------------------------------
# Server internals
# ---------------------------------------------------------------------------

def _ensure_core_managed_start() -> None:
    if os.environ.get("BLUEARCH_CORE_MANAGED_WEB_START") == "1":
        return
    console.print("[yellow]BlueArch web startup is managed by bluearch-aws-core.[/yellow]")
    console.print("[cyan]Run:[/cyan] bluearch-aws-core start --daemon")
    raise typer.Exit(1)


def _resolve_start_port(host: str, preferred: int) -> int:
    """Resolve the startup port for the local dashboard."""
    if preferred in MANAGED_DASHBOARD_PORTS:
        _stop_known_web_servers(preferred)
        if _is_port_available(host, preferred):
            return preferred
        console.print(
            f"[red]Port {preferred} is still in use by a non-BlueArch/Tag Manager process.[/red]"
        )
        console.print("[dim]Stop that process and run `bluearch-aws-core start --daemon` again.[/dim]")
        raise typer.Exit(1)
    return _find_available_port(host, preferred)


def _ensure_core_dependency() -> None:
    try:
        from utils.core_client import MINIMUM_CORE_VERSION, check_core_dependency

        check_core_dependency("bluearch-aws-ops")
    except Exception as exc:
        console.print("[red]bluearch-aws-core is required before starting the BlueArch web dashboard.[/red]")
        console.print(f"[dim]{exc}[/dim]")
        console.print(f"[cyan]Required version:[/cyan] bluearch-aws-core >= {MINIMUM_CORE_VERSION}")
        console.print("[cyan]Start it with:[/cyan] bluearch-aws-core start --daemon")
        console.print("[cyan]Install it with:[/cyan] brew install bluearchio/tap/bluearch-aws-core")
        raise typer.Exit(1)


def _find_available_port(host: str, preferred: int) -> int:
    """Find an available port, starting from the preferred one.

    If the preferred port is in use (e.g. another CLI's web server is running),
    tries the next 20 ports and returns the first available one.
    """
    # For 0.0.0.0 binding, test on 127.0.0.1 (same address space)
    test_host = "127.0.0.1" if host == "0.0.0.0" else host

    for port in range(preferred, preferred + 20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
                s.bind((test_host, port))
                if port != preferred:
                    console.print(f"[yellow]Port {preferred} in use, using {port} instead[/yellow]")
                return port
        except OSError:
            continue
    console.print(f"[red]No available port found in range {preferred}-{preferred + 19}[/red]")
    raise typer.Exit(1)


def _is_port_available(host: str, port: int) -> bool:
    test_host = "127.0.0.1" if host == "0.0.0.0" else host
    if _listener_pids(port):
        return False
    try:
        with socket.create_connection((test_host, port), timeout=0.2):
            return False
    except (ConnectionRefusedError, TimeoutError, OSError):
        return True


def _stop_known_web_servers(target_port: int) -> None:
    """Stop only this app's old server plus any app process on target_port."""
    pids = set()
    pid = _read_pid_file(PID_FILE)
    if pid:
        pids.add(pid)
    pids.update(_listener_pids(target_port))

    stopped = []
    legacy_conflicts = []
    for pid in sorted(pids):
        if pid == os.getpid() or not _is_process_alive(pid):
            continue
        if _is_legacy_ops_process(pid):
            legacy_conflicts.append(pid)
        elif _is_bluearch_or_tag_manager_process(pid):
            _terminate_process(pid)
            stopped.append(pid)

    if stopped:
        console.print(
            f"[yellow]Stopped existing BlueArch/Tag Manager web process(es): {', '.join(map(str, stopped))}[/yellow]"
        )
    if legacy_conflicts:
        console.print(
            "[yellow]Legacy BlueArch dashboard migration conflict detected for process(es): "
            f"{', '.join(map(str, legacy_conflicts))}. Stop or migrate them manually.[/yellow]"
        )
    _remove_stale_pid_files()


def _listener_pids(port: int) -> set[int]:
    pids: set[int] = set()
    try:
        import psutil
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == "LISTEN" and conn.laddr and conn.laddr.port == port and conn.pid:
                pids.add(conn.pid)
    except Exception:
        try:
            proc = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in proc.stdout.splitlines():
                try:
                    pids.add(int(line.strip()))
                except ValueError:
                    pass
        except Exception:
            pass
    return pids


def _is_bluearch_or_tag_manager_process(pid: int) -> bool:
    cmdline = _process_cmdline(pid).lower()
    return any(marker in cmdline for marker in APP_PROCESS_MARKERS)


def _is_legacy_ops_process(pid: int) -> bool:
    cmdline = _process_cmdline(pid).lower()
    return any(marker in cmdline for marker in LEGACY_OPS_PROCESS_MARKERS)


def _process_cmdline(pid: int) -> str:
    try:
        import psutil
        return " ".join(psutil.Process(pid).cmdline())
    except Exception:
        try:
            proc = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                check=False,
            )
            return proc.stdout.strip()
        except Exception:
            return ""


def _terminate_process(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(50):
        if not _is_process_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _read_pid_file(path: str) -> Optional[int]:
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _remove_stale_pid_files() -> None:
    pid = _read_pid_file(PID_FILE)
    if pid is None or not _is_process_alive(pid):
        try:
            os.unlink(PID_FILE)
        except FileNotFoundError:
            pass


def _open_browser(host, port):
    """Open the dashboard URL in the default browser."""
    import webbrowser
    url = f"http://{host}:{port}" if host != "0.0.0.0" else f"http://localhost:{port}"
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _print_urls(host, port):
    """Print dashboard, API docs, and health URLs."""
    display_host = "localhost" if host == "0.0.0.0" else host
    base = f"http://{display_host}:{port}"
    console.print()
    console.print(f"  Dashboard:  [bold cyan]{base}[/bold cyan]")
    console.print(f"  API Docs:   [cyan]{base}/docs[/cyan]")
    console.print(f"  Health:     [cyan]{base}/api/v1/system/health[/cyan]")
    console.print()


def _start_foreground(host, port, log_level="info", no_browser=False):
    """Start uvicorn in the foreground."""
    try:
        import uvicorn
        import fastapi  # noqa: F401
    except ImportError:
        console.print("[red]Missing dependencies: uvicorn and fastapi[/red]")
        console.print("Install with: [cyan]pip install fastapi uvicorn[standard][/cyan]")
        raise typer.Exit(1)

    console.print(f"[green]Starting BlueArch Dashboard on http://{host}:{port}[/green]")
    console.print(f"[dim]Log level: {log_level} | Press Ctrl+C to stop[/dim]")
    _print_urls(host, port)

    if not no_browser:
        import threading
        threading.Timer(1.5, _open_browser, args=(host, port)).start()

    uvicorn.run(
        "web.app:create_app",
        host=host,
        port=port,
        factory=True,
        workers=1,
        log_level=log_level,
    )


def _start_daemon(host, port, log_level="info", no_browser=False):
    """Start the server as a background daemon process."""
    os.makedirs(PID_DIR, exist_ok=True)

    # Create log file, update symlink, prune old logs (matches tag-manager pattern)
    current_log = _rotate_logs()

    cmd = _build_daemon_command(host, port, log_level)

    env = _daemon_child_env()

    with open(current_log, "a") as lf:
        proc = subprocess.Popen(
            cmd,
            stdout=lf,
            stderr=lf,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=_daemon_cwd(),
            env=env,
        )

    _wait_for_daemon_ready(proc, host, port, current_log)

    _write_pid(proc.pid)

    console.print(f"[green]Dashboard started on http://{host}:{port} (PID {proc.pid})[/green]")
    console.print(f"[dim]Log: {current_log}[/dim]")
    console.print(f"[dim]Symlink: {LOG_SYMLINK}[/dim]")
    _print_urls(host, port)

    if not no_browser:
        import threading
        threading.Timer(2.0, _open_browser, args=(host, port)).start()


def _build_daemon_command(host: str, port: int, log_level: str) -> list[str]:
    """Build the child process command for daemon mode."""
    if _is_packaged_runtime() or not _is_python_executable(sys.executable):
        cli_executable = _find_cli_executable()
        if cli_executable is None:
            console.print("[red]Unable to find an executable BlueArch CLI launcher for daemon mode.[/red]")
            console.print("[dim]Run `bluearch-aws-core start --daemon` to start the managed dashboard.[/dim]")
            raise typer.Exit(1)
        return [
            cli_executable,
            "web",
            "start",
            "--host",
            host,
            "--port",
            str(port),
            "--log-level",
            log_level,
            "--no-browser",
        ]

    return [
        sys.executable,
        "-c",
        (
            "import uvicorn; "
            f"uvicorn.run('web.app:create_app', host='{host}', port={port}, "
            f"factory=True, workers=1, log_level='{log_level}')"
        ),
    ]


def _daemon_child_env() -> dict[str, str]:
    """Build environment for the detached web daemon child process."""
    env = os.environ.copy()
    env["BLUEARCH_WEB_DAEMON_CHILD"] = "1"
    if _is_packaged_runtime():
        # PyInstaller onefile apps otherwise let the short-lived parent own the
        # extraction directory. When the parent exits, the child keeps a stale
        # sys._MEIPASS path and bundled frontend assets disappear.
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def _daemon_cwd() -> str:
    """Return a stable working directory for the detached child process."""
    if _is_packaged_runtime() or not _is_python_executable(sys.executable):
        os.makedirs(PID_DIR, exist_ok=True)
        return PID_DIR
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _wait_for_daemon_ready(proc: subprocess.Popen, host: str, port: int, log_path: str) -> None:
    """Wait until the child serves health, or fail before reporting success."""
    health_url = f"http://{_test_host(host)}:{port}/api/v1/system/health"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            console.print(f"[red]Server failed to start. Check log: {log_path}[/red]")
            raise typer.Exit(1)
        try:
            with urllib.request.urlopen(health_url, timeout=0.3) as response:
                if response.status < 500:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.2)

    _terminate_process(proc.pid)
    console.print(f"[red]Server did not become ready at {health_url}. Check log: {log_path}[/red]")
    raise typer.Exit(1)


def _test_host(host: str) -> str:
    return "127.0.0.1" if host == "0.0.0.0" else host


def _find_cli_executable() -> Optional[str]:
    """Find the user-facing CLI launcher instead of assuming sys.executable works."""
    candidates = [
        sys.argv[0] if os.path.basename(sys.argv[0]) == PUBLIC_OPS_EXECUTABLE else None,
        shutil.which(PUBLIC_OPS_EXECUTABLE),
        os.path.join(os.path.expanduser("~"), ".local", "bin", PUBLIC_OPS_EXECUTABLE),
        f"/opt/homebrew/bin/{PUBLIC_OPS_EXECUTABLE}",
        f"/usr/local/bin/{PUBLIC_OPS_EXECUTABLE}",
    ]

    for candidate in candidates:
        if not candidate:
            continue
        if os.path.isabs(candidate) or os.path.dirname(candidate):
            path = candidate
        else:
            path = shutil.which(candidate)
        if not path:
            continue
        resolved = os.path.realpath(os.path.abspath(path))
        if (
            os.path.basename(path) != PUBLIC_OPS_EXECUTABLE
            or os.path.basename(resolved) != PUBLIC_OPS_EXECUTABLE
        ):
            continue
        if os.path.isfile(resolved) and os.access(resolved, os.X_OK):
            return resolved
    return None


def _is_packaged_runtime() -> bool:
    """Return True when running from a frozen/onefile app extraction."""
    return (
        hasattr(sys, "_MEIPASS")
        or getattr(sys, "frozen", False)
        or _is_nuitka_onefile_runtime(sys.executable)
    )


def _is_nuitka_onefile_runtime(path: str) -> bool:
    """Detect the internal runtime extracted by the macOS Nuitka onefile build."""
    if not path:
        return False

    try:
        runtime_dir = os.path.realpath(os.path.join(os.path.expanduser("~"), ".bluearch", "bin"))
        executable_path = os.path.realpath(path)
    except OSError:
        return False

    return executable_path == runtime_dir or executable_path.startswith(runtime_dir + os.sep)


def _looks_like_python_executable(path: str) -> bool:
    executable_name = os.path.basename(path or "").lower()
    return executable_name in ("python", "python3") or executable_name.startswith("python3.")


def _is_python_executable(path: str) -> bool:
    """Return True when path can be used to spawn a Python child process."""
    if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
        return False

    if _is_nuitka_onefile_runtime(path):
        return False

    if not _looks_like_python_executable(path):
        return False

    return True


def _show_status():
    pid = _read_pid()
    running = bool(pid and _is_process_alive(pid))
    if running:
        console.print(f"[green]Server is running (PID {pid})[/green]")
        try:
            import psutil
            proc = psutil.Process(pid)
            uptime = time.time() - proc.create_time()
            hours, remainder = divmod(int(uptime), 3600)
            minutes, seconds = divmod(remainder, 60)
            mem_mb = proc.memory_info().rss / (1024 * 1024)
            console.print(f"  Uptime:  {hours}h {minutes}m {seconds}s")
            console.print(f"  Memory:  {mem_mb:.1f} MB")
        except ImportError:
            pass
        except Exception:
            pass
    else:
        if pid:
            _remove_pid()
        console.print("[dim]Server is not running[/dim]")


def _is_server_running() -> bool:
    pid = _read_pid()
    return pid is not None and _is_process_alive(pid)


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _write_pid(pid: int):
    os.makedirs(PID_DIR, exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(pid))


def _read_pid() -> Optional[int]:
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def _remove_pid():
    try:
        os.unlink(PID_FILE)
    except FileNotFoundError:
        pass


MAX_LOG_FILES = 5
LOG_SYMLINK = os.path.join(PID_DIR, "web-server.log")  # convenience symlink to current log


def _rotate_logs() -> str:
    """Create a new timestamped log file, update symlink, and prune old ones.

    Returns the path to the new log file. Matches tag-manager pattern.
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    new_log = os.path.join(LOG_DIR, f"web-server-{timestamp}.log")

    # Update the convenience symlink
    try:
        if os.path.islink(LOG_SYMLINK) or os.path.exists(LOG_SYMLINK):
            os.unlink(LOG_SYMLINK)
        os.symlink(new_log, LOG_SYMLINK)
    except OSError:
        pass  # Symlinks may not work on all platforms

    # Prune old log files, keep the newest MAX_LOG_FILES
    try:
        logs = sorted(
            [
                os.path.join(LOG_DIR, f)
                for f in os.listdir(LOG_DIR)
                if f.startswith("web-server-") and f.endswith(".log")
            ],
        )
        for stale in logs[:-MAX_LOG_FILES]:
            try:
                os.unlink(stale)
            except OSError:
                pass
    except OSError:
        pass

    return new_log
