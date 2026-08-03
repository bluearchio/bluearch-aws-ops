"""Web dashboard CLI commands — start, stop, status with daemon support.

Usage:
    bluearch-aws-core start --daemon
    bluearch-aws-ops web stop
    bluearch-aws-ops web status
"""

import json
import math
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from typing import Optional

import typer
from rich.console import Console

console = Console()

# Product-specific runtime state prevents one CLI from treating another
# product's PID file as its own. Existing shared data paths are unchanged.
PID_DIR = os.path.join(os.path.expanduser("~"), ".bluearch-aws-ops", "runtime")
PID_FILE = os.path.join(PID_DIR, "web-server.pid")
LOG_DIR = os.path.join(os.path.expanduser("~"), ".bluearch-aws-ops", "logs")
MANAGED_DASHBOARD_PORTS = (8095, 8096)
PUBLIC_OPS_EXECUTABLE = "bluearch-aws-ops"
OPS_WEB_PROCESS_SENTINEL = "bluearch-aws-ops-managed-web"
PID_RECORD_SCHEMA = 2
LEGACY_PID_RECORD_SCHEMA = 1
PID_RECORD_PRODUCT = "io.bluearch.aws.ops.web"
NUITKA_RUNTIME_DIRECTORY_PATTERN = re.compile(
    rf"^{re.escape(PUBLIC_OPS_EXECUTABLE)}_(\d+)_(\d+)_(\d+)$"
)
PROCESS_POLL_INTERVAL_SECONDS = 0.1
DEFAULT_PROCESS_GRACE_SECONDS = 5.0
UNVERIFIED_NUITKA_SUPERVISOR_GRACE_SECONDS = 10.0


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
    record = _read_pid_record()
    if record is None:
        if _pid_file_present():
            console.print(
                "[red]Ops web runtime state is invalid; no process was signaled. "
                f"Inspect {PID_FILE} before retrying.[/red]"
            )
            raise typer.Exit(1)
        console.print("[yellow]No running server found.[/yellow]")
        return

    managed = _managed_runtime_from_record(record)
    if managed is None:
        if _record_processes_are_gone(record):
            _remove_pid()
            console.print("[yellow]No running server found.[/yellow]")
            return
        console.print(
            "[red]Ops web process identity changed; no process was signaled and the state was preserved.[/red]"
        )
        raise typer.Exit(1)

    pid = managed["listener"]["pid"]
    console.print(f"Stopping server (PID {pid})...")
    if not _terminate_managed_runtime(managed):
        console.print("[red]Process identity changed; no unverified process was signaled.[/red]")
        raise typer.Exit(1)

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
        console.print("[cyan]Trust it with:[/cyan] brew trust --formula bluearchio/tap/bluearch-aws-core")
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
    """Stop one verified Ops runtime, keeping listener recovery fail-closed."""
    record = _read_pid_record()
    if record is None and _pid_file_present():
        console.print(
            "[red]Ops web runtime state is invalid; no process was signaled. "
            f"Inspect {PID_FILE} before retrying.[/red]"
        )
        return

    listener_pids = _listener_pids(target_port)
    managed = (
        _managed_runtime_from_record(
            record,
            target_port=target_port,
            listener_pids=listener_pids,
        )
        if record is not None
        else None
    )

    legacy_conflicts: list[int] = []
    if managed is None and record is None:
        candidates: list[dict] = []
        for pid in sorted(listener_pids):
            if pid == os.getpid():
                continue
            snapshot = _process_snapshot(pid)
            if snapshot is None:
                continue
            if _snapshot_is_legacy_ops_web(snapshot):
                legacy_conflicts.append(pid)
            elif _is_strict_current_listener(snapshot, target_port):
                candidates.append(snapshot)
        if len(candidates) == 1:
            listener = candidates[0]
            managed = {
                "listener": listener,
                "listener_identity": _identity_from_snapshot(listener),
                "supervisor": _validated_supervisor_for_listener(listener, target_port),
            }

    stopped = _terminate_managed_runtime(managed) if managed is not None else []
    if stopped is None:
        console.print(
            "[red]The Ops listener stopped, but its verified supervisor is still running; "
            "runtime state was preserved.[/red]"
        )
        raise typer.Exit(1)

    if stopped:
        console.print(
            f"[yellow]Stopped existing BlueArch AWS Ops web process(es): {', '.join(map(str, stopped))}[/yellow]"
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


def _process_snapshot(pid: int) -> Optional[dict]:
    """Return stable process identity data, or None when it cannot be proven."""
    try:
        import psutil

        process = psutil.Process(pid)
        snapshot = {
            "pid": pid,
            "create_time": float(process.create_time()),
            "cmdline": tuple(process.cmdline()),
            "executable": process.exe(),
            "ppid": int(process.ppid()),
            "uid": int(process.uids().effective) if hasattr(process, "uids") else None,
        }
        if not process.is_running():
            return None
        if (
            not snapshot["cmdline"]
            or not snapshot["executable"]
            or not os.path.isabs(snapshot["executable"])
        ):
            return None
        return snapshot
    except Exception:
        return None


def _snapshot_is_public_ops_web(snapshot: dict) -> bool:
    """Require an exact public command or the source-runtime sentinel."""
    cmdline = tuple(str(part) for part in snapshot.get("cmdline", ()))
    if OPS_WEB_PROCESS_SENTINEL in cmdline:
        executable = os.path.basename(str(snapshot.get("executable", ""))).lower()
        return (
            len(cmdline) == 4
            and _snapshot_owned_by_current_user(snapshot)
            and _looks_like_python_executable(executable)
            and cmdline[1] == "-c"
            and "uvicorn.run('web.app:create_app'" in cmdline[2]
            and cmdline[3] == OPS_WEB_PROCESS_SENTINEL
        )
    if len(cmdline) < 3 or not _snapshot_owned_by_current_user(snapshot):
        return False
    if cmdline[1:3] != ("web", "start"):
        return False
    command_executable = os.path.basename(cmdline[0])
    executable_path = str(snapshot.get("executable", ""))
    executable = os.path.basename(executable_path)
    packaged_runtime = _is_expected_nuitka_ops_executable(executable_path, snapshot)
    command_runtime = _is_expected_nuitka_ops_executable(cmdline[0], snapshot)
    return (
        (
            command_executable == PUBLIC_OPS_EXECUTABLE
            and (
                (executable == PUBLIC_OPS_EXECUTABLE and _is_exact_packaged_daemon_argv(cmdline))
                or (packaged_runtime and _is_exact_packaged_daemon_argv(cmdline))
            )
        )
        or (
            command_executable == f"{PUBLIC_OPS_EXECUTABLE}.bin"
            and command_runtime
            and packaged_runtime
            and _is_exact_packaged_daemon_argv(cmdline, allow_runtime_argv0=True)
            and os.path.realpath(cmdline[0]) == os.path.realpath(executable_path)
        )
    )


def _snapshot_is_legacy_ops_web(snapshot: dict) -> bool:
    cmdline = tuple(str(part) for part in snapshot.get("cmdline", ()))
    if len(cmdline) < 3:
        return False
    return os.path.basename(cmdline[0]) == "bluearch" and cmdline[1:3] == ("web", "start")


def _same_process(pid: int, expected_create_time: float) -> Optional[dict]:
    snapshot = _process_snapshot(pid)
    if snapshot is None:
        return None
    if abs(snapshot["create_time"] - expected_create_time) > 0.001:
        return None
    if not _snapshot_is_public_ops_web(snapshot):
        return None
    return snapshot


def _snapshot_owned_by_current_user(snapshot: dict) -> bool:
    if not hasattr(os, "getuid"):
        return True
    return snapshot.get("uid") == os.getuid()


def _identity_from_snapshot(snapshot: dict) -> dict:
    # PPID is deliberately not persisted: the detached supervisor (and the
    # direct source listener) is re-parented as soon as the launching CLI exits.
    # Parent/child topology is proven while both snapshots are live instead.
    return {
        "pid": snapshot["pid"],
        "create_time": snapshot["create_time"],
        "argv": list(snapshot["cmdline"]),
        "executable": snapshot["executable"],
        "uid": snapshot.get("uid"),
    }


def _identity_matches_snapshot(identity: dict, snapshot: Optional[dict]) -> bool:
    if snapshot is None:
        return False
    return (
        identity["pid"] == snapshot["pid"]
        and abs(identity["create_time"] - snapshot["create_time"]) <= 0.001
        and tuple(identity["argv"]) == tuple(snapshot["cmdline"])
        and identity["executable"] == snapshot["executable"]
        and identity.get("uid") == snapshot.get("uid")
        and _snapshot_owned_by_current_user(snapshot)
    )


def _recaptured_snapshot_matches(expected: dict) -> bool:
    return _identity_matches_snapshot(
        _identity_from_snapshot(expected),
        _process_snapshot(expected["pid"]),
    )


def _terminate_process(
    pid: int,
    expected_create_time: float,
    *,
    expected_snapshot: Optional[dict] = None,
    expected_identity: Optional[dict] = None,
    grace_seconds: float = DEFAULT_PROCESS_GRACE_SECONDS,
) -> bool:
    """Signal only the exact captured process; never follow a reused PID."""
    snapshot = expected_snapshot or _process_snapshot(pid)
    identity = expected_identity or (
        _identity_from_snapshot(snapshot) if snapshot is not None else None
    )
    if (
        snapshot is None
        or identity is None
        or snapshot["pid"] != pid
        or abs(snapshot["create_time"] - expected_create_time) > 0.001
        or not _identity_matches_snapshot(identity, snapshot)
        or not _snapshot_is_public_ops_web(snapshot)
        or not _recaptured_snapshot_matches(snapshot)
    ):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    attempts = max(1, math.ceil(grace_seconds / PROCESS_POLL_INTERVAL_SECONDS))
    for _ in range(attempts):
        current = _process_snapshot(pid)
        if current is None:
            if _process_is_gone_or_zombie(pid):
                return True
            time.sleep(PROCESS_POLL_INTERVAL_SECONDS)
            continue
        if not _identity_matches_snapshot(identity, current):
            # The original process is gone and this PID now belongs to
            # something else. Never signal the replacement.
            return True
        time.sleep(PROCESS_POLL_INTERVAL_SECONDS)
    current = _process_snapshot(pid)
    if current is None:
        return _process_is_gone_or_zombie(pid)
    if not _identity_matches_snapshot(identity, current):
        return True
    if not _recaptured_snapshot_matches(current):
        return False
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    return True


def _remove_stale_pid_files() -> None:
    record = _read_pid_record()
    if record is None:
        return
    if _record_processes_are_gone(record):
        _remove_pid()


def _terminate_managed_runtime(managed: Optional[dict]) -> Optional[list[int]]:
    """Stop the listener first, then its exact Nuitka supervisor."""
    if managed is None:
        return None
    listener = managed["listener"]
    if listener["pid"] == os.getpid() or not _terminate_process(
        listener["pid"],
        listener["create_time"],
        expected_snapshot=listener,
        expected_identity=managed["listener_identity"],
    ):
        return None

    stopped = [listener["pid"]]
    supervisor = managed.get("supervisor")
    if supervisor is not None and supervisor["pid"] != listener["pid"]:
        supervisor_identity = _identity_from_snapshot(supervisor)
        current = _process_snapshot(supervisor["pid"])
        if current is None:
            return stopped if _process_is_gone_or_zombie(supervisor["pid"]) else None
        if not _identity_matches_snapshot(supervisor_identity, current):
            if abs(current["create_time"] - supervisor["create_time"]) > 0.001:
                return stopped  # PID reuse: never signal the replacement.
            return None
        if _terminate_process(
            supervisor["pid"],
            supervisor["create_time"],
            expected_snapshot=current,
            expected_identity=supervisor_identity,
        ):
            stopped.append(supervisor["pid"])
        else:
            current = _process_snapshot(supervisor["pid"])
            if current is None:
                return stopped if _process_is_gone_or_zombie(supervisor["pid"]) else None
            if abs(current["create_time"] - supervisor["create_time"]) > 0.001:
                return stopped
            return None
    return stopped


def _process_is_gone_or_zombie(pid: int) -> bool:
    try:
        import psutil
    except Exception:
        return not _is_process_alive(pid)
    try:
        process = psutil.Process(pid)
        return process.status() == psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, ProcessLookupError):
        return True
    except Exception:
        return False


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

    spawned = _process_snapshot(proc.pid)
    if spawned is None or not _snapshot_is_public_ops_web(spawned):
        _terminate_child_process(proc)
        console.print(
            "[red]Could not establish a stable identity for the spawned Ops web process.[/red]"
        )
        raise typer.Exit(1)

    _wait_for_daemon_ready(
        proc,
        host,
        port,
        current_log,
        expected_snapshot=spawned,
    )

    managed = _resolve_spawned_daemon_runtime(spawned, port)
    if managed is None:
        _cleanup_spawned_runtime(spawned, port)
        console.print(
            "[red]The ready Ops listener did not match the spawned process; no runtime state was persisted.[/red]"
        )
        raise typer.Exit(1)

    try:
        _write_pid(
            managed["listener"]["pid"],
            snapshot=managed["listener"],
            supervisor=managed.get("supervisor"),
        )
    except RuntimeError as exc:
        _terminate_managed_runtime(managed)
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    listener_pid = managed["listener"]["pid"]
    console.print(f"[green]Dashboard started on http://{host}:{port} (PID {listener_pid})[/green]")
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
        OPS_WEB_PROCESS_SENTINEL,
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


def _wait_for_daemon_ready(
    proc: subprocess.Popen,
    host: str,
    port: int,
    log_path: str,
    *,
    expected_snapshot: dict,
) -> None:
    """Wait until the child serves health, or fail before reporting success."""
    health_url = f"http://{_test_host(host)}:{port}/api/v1/system/health"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            _cleanup_spawned_runtime(expected_snapshot, port)
            console.print(f"[red]Server failed to start. Check log: {log_path}[/red]")
            raise typer.Exit(1)
        try:
            with urllib.request.urlopen(health_url, timeout=0.3) as response:
                if response.status < 500:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.2)

    _cleanup_spawned_runtime(expected_snapshot, port)
    console.print(f"[red]Server did not become ready at {health_url}. Check log: {log_path}[/red]")
    raise typer.Exit(1)


def _resolve_spawned_daemon_runtime(spawned: dict, port: int) -> Optional[dict]:
    """Bind the listening PID to the exact process created by daemon mode."""
    return _captured_runtime_for_spawned(spawned, port, require_health=True)


def _captured_runtime_for_spawned(
    spawned: dict,
    port: int,
    *,
    require_health: bool,
) -> Optional[dict]:
    """Capture only a listener provably descended from the recorded spawn."""
    current = _process_snapshot(spawned["pid"])
    current_is_spawned = _identity_matches_snapshot(
        _identity_from_snapshot(spawned), current
    )
    listener_pids = _listener_pids(port)
    if current_is_spawned and current["pid"] in listener_pids:
        if (
            _snapshot_is_public_ops_web(current)
            and (not require_health or _probe_ops_health(port))
            and _recaptured_snapshot_matches(current)
        ):
            return {
                "listener": current,
                "listener_identity": _identity_from_snapshot(current),
                "supervisor": None,
            }
        return None

    candidates: list[dict] = []
    for listener_pid in sorted(listener_pids):
        listener = _process_snapshot(listener_pid)
        if (
            listener is not None
            and _listener_matches_spawned_snapshot(listener, spawned, port)
        ):
            candidates.append(listener)
    if (
        len(candidates) != 1
        or not _is_exact_packaged_daemon_argv(
            tuple(spawned.get("cmdline", ())), target_port=port
        )
        or os.path.basename(str(spawned.get("executable", "")))
        != PUBLIC_OPS_EXECUTABLE
        or (require_health and not _probe_ops_health(port))
        or (current_is_spawned and not _recaptured_snapshot_matches(current))
        or not _recaptured_snapshot_matches(candidates[0])
    ):
        return None
    return {
        "listener": candidates[0],
        "listener_identity": _identity_from_snapshot(candidates[0]),
        "supervisor": current if current_is_spawned else None,
    }


def _listener_matches_spawned_snapshot(listener: dict, spawned: dict, port: int) -> bool:
    if (
        tuple(listener.get("cmdline", ())) != tuple(spawned.get("cmdline", ()))
        or listener.get("uid") != spawned.get("uid")
        or not _is_nuitka_listener_snapshot(
            listener,
            target_port=port,
            require_current_launcher=False,
            expected_supervisor_pid=spawned["pid"],
        )
    ):
        return False
    if listener.get("ppid") == spawned["pid"]:
        return True

    # If the supervisor exited before cleanup, the listener may already be
    # re-parented. The onefile root still embeds the exact captured supervisor
    # PID (or uses the legacy product-specific fixed directory).
    runtime_root = _nuitka_onefile_runtime_root(listener["executable"])
    if runtime_root is None:
        return False
    legacy_root = os.path.realpath(
        os.path.join(os.path.expanduser("~"), ".bluearch-aws-ops", "bin")
    )
    if runtime_root == legacy_root:
        return _process_snapshot(spawned["pid"]) is None
    match = NUITKA_RUNTIME_DIRECTORY_PATTERN.fullmatch(os.path.basename(runtime_root))
    return (
        match is not None
        and int(match.group(1)) == spawned["pid"]
        and _process_snapshot(spawned["pid"]) is None
    )


def _cleanup_spawned_runtime(spawned: dict, port: int) -> bool:
    """Clean a failed spawn without ever terminating its supervisor first."""
    managed = _captured_runtime_for_spawned(spawned, port, require_health=False)
    if managed is not None:
        return _terminate_managed_runtime(managed) is not None

    current = _process_snapshot(spawned["pid"])
    identity = _identity_from_snapshot(spawned)
    if not _identity_matches_snapshot(identity, current):
        return _process_is_gone_or_zombie(spawned["pid"])
    return _terminate_process(
        current["pid"],
        current["create_time"],
        expected_snapshot=current,
        expected_identity=identity,
        grace_seconds=UNVERIFIED_NUITKA_SUPERVISOR_GRACE_SECONDS,
    )


def _terminate_child_process(proc: subprocess.Popen) -> None:
    """Terminate a child handle created by this process without PID discovery."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=UNVERIFIED_NUITKA_SUPERVISOR_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=UNVERIFIED_NUITKA_SUPERVISOR_GRACE_SECONDS)


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


def _nuitka_onefile_runtime_root(path: str) -> Optional[str]:
    """Return an exact legacy or unique product extraction root for a path."""
    if not path or not os.path.isabs(path):
        return None
    try:
        executable_path = os.path.realpath(path)
        legacy_root = os.path.realpath(
            os.path.join(os.path.expanduser("~"), ".bluearch-aws-ops", "bin")
        )
        if executable_path == legacy_root or executable_path.startswith(
            legacy_root + os.sep
        ):
            return legacy_root

        temp_root = os.path.realpath(tempfile.gettempdir())
        if os.path.commonpath((temp_root, executable_path)) != temp_root:
            return None
        relative = os.path.relpath(executable_path, temp_root)
    except (OSError, ValueError):
        return None

    parts = relative.split(os.sep)
    if not parts or parts[0] in {"", os.curdir, os.pardir}:
        return None
    match = NUITKA_RUNTIME_DIRECTORY_PATTERN.fullmatch(parts[0])
    if (
        match is None
        or int(match.group(1)) <= 0
        or int(match.group(2)) <= 0
        or not 0 <= int(match.group(3)) < 1_000_000
    ):
        return None
    return os.path.join(temp_root, parts[0])


def _is_expected_nuitka_ops_executable(
    path: str,
    snapshot: dict,
    *,
    expected_supervisor_pid: Optional[int] = None,
) -> bool:
    """Recognize only the shipped legacy path or unique Ops extraction path."""
    if (
        not path
        or not os.path.isabs(path)
        or os.path.basename(path) != f"{PUBLIC_OPS_EXECUTABLE}.bin"
        or os.path.islink(path)
    ):
        return False
    runtime_root = _nuitka_onefile_runtime_root(path)
    executable_path = os.path.realpath(path)
    if runtime_root is None or os.path.dirname(executable_path) != runtime_root:
        return False
    if hasattr(os, "getuid") and snapshot.get("uid") != os.getuid():
        return False

    legacy_root = os.path.realpath(
        os.path.join(os.path.expanduser("~"), ".bluearch-aws-ops", "bin")
    )
    if runtime_root == legacy_root:
        return True

    match = NUITKA_RUNTIME_DIRECTORY_PATTERN.fullmatch(os.path.basename(runtime_root))
    if match is None:
        return False
    extraction_pid = int(match.group(1))
    return extraction_pid in {
        value
        for value in (
            snapshot.get("pid"),
            snapshot.get("ppid"),
            expected_supervisor_pid,
        )
        if isinstance(value, int) and value > 0
    }


def _is_nuitka_onefile_runtime(path: str) -> bool:
    """Detect an internal runtime from the legacy or unique onefile layout."""
    return _nuitka_onefile_runtime_root(path) is not None


def _is_exact_packaged_daemon_argv(
    cmdline: tuple[str, ...],
    *,
    target_port: Optional[int] = None,
    allow_runtime_argv0: bool = False,
) -> bool:
    """Match only the public, loopback, non-daemon child invocation."""
    if len(cmdline) != 10 or not os.path.isabs(cmdline[0]):
        return False
    expected_names = {PUBLIC_OPS_EXECUTABLE}
    if allow_runtime_argv0:
        expected_names.add(f"{PUBLIC_OPS_EXECUTABLE}.bin")
    if os.path.basename(cmdline[0]) not in expected_names:
        return False
    if (
        cmdline[1:4] != ("web", "start", "--host")
        or cmdline[4] not in {"127.0.0.1", "localhost", "::1"}
        or cmdline[5] != "--port"
        or cmdline[7] != "--log-level"
        or cmdline[8] not in {"debug", "info", "warning", "error", "critical"}
        or cmdline[9] != "--no-browser"
    ):
        return False
    try:
        port = int(cmdline[6])
    except ValueError:
        return False
    return 1 <= port <= 65535 and (target_port is None or port == target_port)


def _homebrew_formula_root(path: Optional[str]) -> Optional[str]:
    """Return the exact bluearch-aws-ops formula root for a Cellar binary."""
    if not path or not os.path.isabs(path) or os.path.basename(path) != PUBLIC_OPS_EXECUTABLE:
        return None
    parts = os.path.normpath(path).split(os.sep)
    try:
        cellar_index = parts.index("Cellar")
    except ValueError:
        return None
    if (
        len(parts) != cellar_index + 5
        or parts[cellar_index + 1] != PUBLIC_OPS_EXECUTABLE
        or not parts[cellar_index + 2]
        or parts[cellar_index + 3] != "bin"
        or parts[cellar_index + 4] != PUBLIC_OPS_EXECUTABLE
    ):
        return None
    return os.sep.join(parts[: cellar_index + 2]) or os.sep


def _current_public_ops_target() -> Optional[str]:
    target = _find_cli_executable()
    if target is None or os.path.islink(target):
        return None
    return target


def _is_formula_supervisor_snapshot(
    snapshot: dict,
    *,
    target_port: Optional[int] = None,
) -> bool:
    cmdline = tuple(snapshot.get("cmdline", ()))
    executable = str(snapshot.get("executable", ""))
    return (
        _snapshot_owned_by_current_user(snapshot)
        and _is_exact_packaged_daemon_argv(cmdline, target_port=target_port)
        and os.path.basename(executable) == PUBLIC_OPS_EXECUTABLE
        and _homebrew_formula_root(cmdline[0]) is not None
        and _homebrew_formula_root(cmdline[0]) == _homebrew_formula_root(executable)
    )


def _is_nuitka_listener_snapshot(
    snapshot: dict,
    *,
    target_port: Optional[int] = None,
    require_current_launcher: bool,
    expected_supervisor_pid: Optional[int] = None,
) -> bool:
    cmdline = tuple(snapshot.get("cmdline", ()))
    if not _snapshot_owned_by_current_user(snapshot):
        return False
    if not _is_exact_packaged_daemon_argv(
        cmdline,
        target_port=target_port,
        allow_runtime_argv0=True,
    ):
        return False
    if not _is_expected_nuitka_ops_executable(
        str(snapshot.get("executable", "")),
        snapshot,
        expected_supervisor_pid=expected_supervisor_pid,
    ):
        return False
    if not require_current_launcher:
        return True
    current = _current_public_ops_target()
    if current is None or os.path.basename(cmdline[0]) != PUBLIC_OPS_EXECUTABLE:
        return False
    return (
        _homebrew_formula_root(cmdline[0]) is not None
        and os.path.normpath(cmdline[0]) == os.path.normpath(current)
    )


def _probe_ops_health(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v1/system/health",
            timeout=0.5,
        ) as response:
            if response.status >= 500:
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("service") == PUBLIC_OPS_EXECUTABLE


def _validated_supervisor_for_listener(
    listener: dict,
    target_port: Optional[int] = None,
) -> Optional[dict]:
    if not _is_nuitka_listener_snapshot(
        listener,
        target_port=target_port,
        require_current_launcher=False,
    ):
        return None
    ppid = listener.get("ppid")
    if not isinstance(ppid, int) or ppid <= 1:
        return None
    supervisor = _process_snapshot(ppid)
    if (
        supervisor is None
        or not _snapshot_owned_by_current_user(supervisor)
        or not _is_exact_packaged_daemon_argv(
            tuple(supervisor.get("cmdline", ())), target_port=target_port
        )
        or os.path.basename(str(supervisor.get("executable", "")))
        != PUBLIC_OPS_EXECUTABLE
        or tuple(supervisor.get("cmdline", ())) != tuple(listener.get("cmdline", ()))
        or supervisor.get("uid") != listener.get("uid")
        or listener.get("ppid") != supervisor.get("pid")
        or not _recaptured_snapshot_matches(supervisor)
        or not _recaptured_snapshot_matches(listener)
    ):
        return None
    return supervisor


def _is_strict_current_listener(snapshot: dict, target_port: int) -> bool:
    """Allow recordless cleanup only for the currently installed formula."""
    if snapshot["pid"] not in _listener_pids(target_port):
        return False
    if not _probe_ops_health(target_port):
        return False
    if _is_nuitka_listener_snapshot(
        snapshot,
        target_port=target_port,
        require_current_launcher=True,
    ):
        return _recaptured_snapshot_matches(snapshot)
    current = _current_public_ops_target()
    return (
        current is not None
        and snapshot.get("executable") == current
        and _snapshot_is_public_ops_web(snapshot)
        and _recaptured_snapshot_matches(snapshot)
    )


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
    record = _read_pid_record()
    managed = _managed_runtime_from_record(record) if record is not None else None
    if managed is not None:
        pid = managed["listener"]["pid"]
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
    elif record is not None and not _record_processes_are_gone(record):
        console.print("[red]Server state is present but its process identity could not be verified.[/red]")
    elif _pid_file_present() and record is None:
        console.print("[red]Server state is invalid and was preserved for inspection.[/red]")
    else:
        _remove_pid()
        console.print("[dim]Server is not running[/dim]")


def _is_server_running() -> bool:
    record = _read_pid_record()
    return record is not None and _managed_runtime_from_record(record) is not None


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _write_pid(
    pid: int,
    *,
    snapshot: Optional[dict] = None,
    supervisor: Optional[dict] = None,
    allow_missing_paths: bool = False,
) -> None:
    """Persist complete listener and optional onefile-supervisor identities."""
    snapshot = snapshot or _process_snapshot(pid)
    if (
        snapshot is None
        or snapshot["pid"] != pid
        or not _snapshot_is_public_ops_web(snapshot)
        or not _recaptured_snapshot_matches(snapshot)
        or not _snapshot_paths_safe_for_persistence(
            snapshot, allow_missing=allow_missing_paths
        )
    ):
        raise RuntimeError("Refusing to record an unverified BlueArch AWS Ops web process")
    if supervisor is not None:
        if (
            supervisor["pid"] == snapshot["pid"]
            or snapshot.get("ppid") != supervisor["pid"]
            or tuple(snapshot.get("cmdline", ())) != tuple(supervisor.get("cmdline", ()))
            or snapshot.get("uid") != supervisor.get("uid")
            or not _snapshot_is_public_ops_web(supervisor)
            or not _recaptured_snapshot_matches(supervisor)
            or not _snapshot_paths_safe_for_persistence(
                supervisor, allow_missing=allow_missing_paths
            )
        ):
            raise RuntimeError("Refusing to record an unverified BlueArch AWS Ops supervisor")

    payload = {
        "schema": PID_RECORD_SCHEMA,
        "product": PID_RECORD_PRODUCT,
        "command": PUBLIC_OPS_EXECUTABLE,
        "listener": _identity_from_snapshot(snapshot),
        "supervisor": _identity_from_snapshot(supervisor) if supervisor is not None else None,
    }
    _atomic_write_pid_record(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def _read_pid_record() -> Optional[dict]:
    raw = _read_trusted_pid_file()
    if raw is None:
        return None
    try:
        record = json.loads(raw)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict) or record.get("command") != PUBLIC_OPS_EXECUTABLE:
        return None

    if record.get("schema") == LEGACY_PID_RECORD_SCHEMA:
        if not _valid_pid(record.get("pid")) or not _valid_create_time(record.get("create_time")):
            return None
        return {
            "schema": LEGACY_PID_RECORD_SCHEMA,
            "command": PUBLIC_OPS_EXECUTABLE,
            "pid": record["pid"],
            "create_time": float(record["create_time"]),
        }

    if (
        record.get("schema") != PID_RECORD_SCHEMA
        or record.get("product") != PID_RECORD_PRODUCT
    ):
        return None
    listener = _validated_identity_payload(record.get("listener"))
    supervisor_payload = record.get("supervisor")
    supervisor = (
        None
        if supervisor_payload is None
        else _validated_identity_payload(supervisor_payload)
    )
    if listener is None or (supervisor_payload is not None and supervisor is None):
        return None
    return {
        "schema": PID_RECORD_SCHEMA,
        "product": PID_RECORD_PRODUCT,
        "command": PUBLIC_OPS_EXECUTABLE,
        "listener": listener,
        "supervisor": supervisor,
    }


def _record_matches_process(record: dict) -> bool:
    return _managed_runtime_from_record(record) is not None


def _read_pid() -> Optional[int]:
    """Compatibility helper returning only a verified Ops daemon PID."""
    record = _read_pid_record()
    managed = _managed_runtime_from_record(record) if record is not None else None
    return managed["listener"]["pid"] if managed is not None else None


def _remove_pid():
    try:
        os.unlink(PID_FILE)
    except FileNotFoundError:
        pass


def _pid_file_present() -> bool:
    return os.path.lexists(PID_FILE)


def _valid_pid(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _valid_create_time(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _validated_identity_payload(payload) -> Optional[dict]:
    if not isinstance(payload, dict):
        return None
    pid = payload.get("pid")
    create_time = payload.get("create_time")
    argv = payload.get("argv")
    executable = payload.get("executable")
    uid = payload.get("uid")
    if (
        not _valid_pid(pid)
        or not _valid_create_time(create_time)
        or not isinstance(argv, list)
        or not argv
        or not all(isinstance(part, str) and part for part in argv)
        or not isinstance(executable, str)
        or not os.path.isabs(executable)
        or (
            uid is not None
            and (isinstance(uid, bool) or not isinstance(uid, int) or uid < 0)
        )
    ):
        return None
    return {
        "pid": pid,
        "create_time": float(create_time),
        "argv": list(argv),
        "executable": executable,
        "uid": uid,
    }


def _read_trusted_pid_file() -> Optional[str]:
    descriptor = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(PID_FILE, flags)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > 128 * 1024
            or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
            or metadata.st_mode & 0o022
        ):
            return None
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = None
            return stream.read(128 * 1024 + 1)
    except (FileNotFoundError, OSError, UnicodeError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _atomic_write_pid_record(content: str) -> None:
    os.makedirs(PID_DIR, mode=0o700, exist_ok=True)
    directory_metadata = os.lstat(PID_DIR)
    existing_metadata = os.lstat(PID_FILE) if os.path.lexists(PID_FILE) else None
    if (
        not stat.S_ISDIR(directory_metadata.st_mode)
        or stat.S_ISLNK(directory_metadata.st_mode)
        or (hasattr(os, "getuid") and directory_metadata.st_uid != os.getuid())
        or directory_metadata.st_mode & 0o022
        or (
            existing_metadata is not None
            and (
                not stat.S_ISREG(existing_metadata.st_mode)
                or stat.S_ISLNK(existing_metadata.st_mode)
                or (
                    hasattr(os, "getuid")
                    and existing_metadata.st_uid != os.getuid()
                )
                or existing_metadata.st_mode & 0o022
            )
        )
    ):
        raise RuntimeError("Refusing to write Ops runtime state through an untrusted path")

    temporary = os.path.join(PID_DIR, f".{os.path.basename(PID_FILE)}.{os.getpid()}.{time.time_ns()}.tmp")
    descriptor = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, PID_FILE)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _snapshot_paths_safe_for_persistence(
    snapshot: dict,
    *,
    allow_missing: bool = False,
) -> bool:
    paths = [str(snapshot.get("executable", ""))]
    cmdline = tuple(snapshot.get("cmdline", ()))
    if cmdline and os.path.isabs(cmdline[0]):
        paths.append(cmdline[0])
    for path in paths:
        if not path or not os.path.isabs(path) or os.path.islink(path):
            return False
        if not os.path.isfile(path) and not allow_missing:
            return False
    return True


def _managed_runtime_from_record(
    record: Optional[dict],
    *,
    target_port: Optional[int] = None,
    listener_pids: Optional[set[int]] = None,
) -> Optional[dict]:
    if record is None:
        return None
    if record["schema"] == LEGACY_PID_RECORD_SCHEMA:
        return _migrate_legacy_pid_record(
            record,
            target_port=target_port,
            listener_pids=listener_pids,
        )

    listener_identity = record["listener"]
    listener = _process_snapshot(listener_identity["pid"])
    if (
        not _identity_matches_snapshot(listener_identity, listener)
        or not _snapshot_is_public_ops_web(listener)
    ):
        return None
    if target_port is not None:
        candidates = listener_pids if listener_pids is not None else _listener_pids(target_port)
        if listener["pid"] not in candidates or not _probe_ops_health(target_port):
            return None

    supervisor = None
    supervisor_identity = record.get("supervisor")
    if supervisor_identity is not None:
        candidate = _process_snapshot(supervisor_identity["pid"])
        if (
            _identity_matches_snapshot(supervisor_identity, candidate)
            and _snapshot_is_public_ops_web(candidate)
            and listener.get("ppid") == candidate["pid"]
            and tuple(listener.get("cmdline", ())) == tuple(candidate.get("cmdline", ()))
            and listener.get("uid") == candidate.get("uid")
        ):
            supervisor = candidate
    return {
        "listener": listener,
        "listener_identity": listener_identity,
        "supervisor": supervisor,
    }


def _migrate_legacy_pid_record(
    record: dict,
    *,
    target_port: Optional[int],
    listener_pids: Optional[set[int]],
) -> Optional[dict]:
    """Migrate the 0.13.7 supervisor-only record after proving its listener."""
    recorded = _process_snapshot(record["pid"])
    if (
        recorded is None
        or abs(recorded["create_time"] - record["create_time"]) > 0.001
        or not _snapshot_is_public_ops_web(recorded)
        or not _recaptured_snapshot_matches(recorded)
    ):
        return None

    ports = (target_port,) if target_port is not None else MANAGED_DASHBOARD_PORTS
    selected_listener = None
    selected_supervisor = None
    for port in ports:
        current_listeners = (
            listener_pids
            if target_port == port and listener_pids is not None
            else _listener_pids(port)
        )
        if recorded["pid"] in current_listeners and _probe_ops_health(port):
            selected_listener = recorded
            break
        children = []
        for pid in sorted(current_listeners):
            child = _process_snapshot(pid)
            if (
                child is not None
                and child.get("ppid") == recorded["pid"]
                and tuple(child.get("cmdline", ())) == tuple(recorded.get("cmdline", ()))
                and child.get("uid") == recorded.get("uid")
                and _is_nuitka_listener_snapshot(
                    child,
                    target_port=port,
                    require_current_launcher=False,
                )
            ):
                children.append(child)
        if len(children) == 1 and _probe_ops_health(port):
            selected_listener = children[0]
            selected_supervisor = recorded
            break

    if (
        selected_listener is None
        or not _recaptured_snapshot_matches(selected_listener)
        or not _recaptured_snapshot_matches(recorded)
        or _read_pid_record() != record
    ):
        return None
    _write_pid(
        selected_listener["pid"],
        snapshot=selected_listener,
        supervisor=selected_supervisor,
        allow_missing_paths=True,
    )
    return {
        "listener": selected_listener,
        "listener_identity": _identity_from_snapshot(selected_listener),
        "supervisor": selected_supervisor,
    }


def _record_processes_are_gone(record: dict) -> bool:
    if record["schema"] == LEGACY_PID_RECORD_SCHEMA:
        pids = [record["pid"]]
    else:
        pids = [record["listener"]["pid"]]
        if record.get("supervisor") is not None:
            pids.append(record["supervisor"]["pid"])
    if any(_is_process_alive(pid) for pid in pids):
        return False
    # A legacy supervisor can disappear while leaving its listener orphaned.
    # Preserve the record for an exact public Ops listener, but do not let an
    # unrelated product on the other managed port keep stale Ops state forever.
    for port in MANAGED_DASHBOARD_PORTS:
        for pid in _listener_pids(port):
            snapshot = _process_snapshot(pid)
            if snapshot is None or _snapshot_is_public_ops_web(snapshot):
                return False
    return True


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
