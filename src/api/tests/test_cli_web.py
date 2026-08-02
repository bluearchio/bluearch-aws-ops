import os
import sys

import pytest
import typer

from cli import web


@pytest.fixture
def packaged_runtime(monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/bluearch-bundle", raising=False)
    yield
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)


def test_daemon_command_uses_cli_launcher_when_packaged(monkeypatch, tmp_path, packaged_runtime):
    launcher = tmp_path / "bluearch-aws-ops"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)

    bundled_python = tmp_path / "python"
    bundled_python.write_text("# not executable\n")
    bundled_python.chmod(0o644)

    monkeypatch.setattr(sys, "argv", [str(launcher)])
    monkeypatch.setattr(sys, "executable", str(bundled_python))
    monkeypatch.setattr(web.shutil, "which", lambda command: None)

    cmd = web._build_daemon_command("127.0.0.1", 8095, "info")

    assert cmd == [
        str(launcher),
        "web",
        "start",
        "--host",
        "127.0.0.1",
        "--port",
        "8095",
        "--log-level",
        "info",
        "--no-browser",
    ]


def test_process_snapshot_uses_real_declared_runtime_dependency():
    """Exercise psutil itself so clean installs cannot pass on mocked snapshots."""
    snapshot = web._process_snapshot(os.getpid())

    assert snapshot is not None
    assert snapshot["pid"] == os.getpid()
    assert snapshot["create_time"] > 0
    assert snapshot["cmdline"]
    assert os.path.isabs(snapshot["executable"])


def test_daemon_command_uses_cli_launcher_when_sys_executable_is_not_python(monkeypatch, tmp_path):
    launcher = tmp_path / "bluearch-aws-ops"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)

    bundled_python = tmp_path / "python"
    bundled_python.write_text("# not executable\n")
    bundled_python.chmod(0o644)

    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "argv", [str(launcher)])
    monkeypatch.setattr(sys, "executable", str(bundled_python))
    monkeypatch.setattr(web.shutil, "which", lambda command: None)

    cmd = web._build_daemon_command("127.0.0.1", 8095, "info")

    assert cmd[0] == str(launcher)
    assert cmd[1:4] == ["web", "start", "--host"]


def test_daemon_command_uses_cli_launcher_for_nuitka_onefile_runtime(monkeypatch, tmp_path):
    launcher = tmp_path / "bluearch-aws-ops"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)

    runtime_dir = tmp_path / ".bluearch-aws-ops" / "bin"
    runtime_dir.mkdir(parents=True)
    bundled_python = runtime_dir / "python"
    bundled_python.write_text("# internal runtime\n")
    bundled_python.chmod(0o755)

    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setenv("HOME", os.fspath(tmp_path))
    monkeypatch.setattr(sys, "argv", [str(launcher)])
    monkeypatch.setattr(sys, "executable", str(bundled_python))
    monkeypatch.setattr(web.shutil, "which", lambda command: None)

    cmd = web._build_daemon_command("127.0.0.1", 8095, "info")

    assert cmd == [
        str(launcher),
        "web",
        "start",
        "--host",
        "127.0.0.1",
        "--port",
        "8095",
        "--log-level",
        "info",
        "--no-browser",
    ]


def test_daemon_command_resolves_relative_cli_launcher(monkeypatch, tmp_path, packaged_runtime):
    launcher = tmp_path / "src" / "api" / "dist" / "bluearch-aws-ops"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)

    bundled_python = tmp_path / "python"
    bundled_python.write_text("# not executable\n")
    bundled_python.chmod(0o644)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["./src/api/dist/bluearch-aws-ops"])
    monkeypatch.setattr(sys, "executable", str(bundled_python))
    monkeypatch.setattr(web.shutil, "which", lambda command: None)

    cmd = web._build_daemon_command("127.0.0.1", 8099, "info")

    assert cmd[0] == os.path.realpath(launcher)
    assert cmd[1:] == [
        "web",
        "start",
        "--host",
        "127.0.0.1",
        "--port",
        "8099",
        "--log-level",
        "info",
        "--no-browser",
    ]


def test_daemon_command_uses_uvicorn_directly_in_source_runtime(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    cmd = web._build_daemon_command("127.0.0.1", 8095, "debug")

    assert cmd[0] == sys.executable
    assert cmd[1] == "-c"
    assert "uvicorn.run('web.app:create_app'" in cmd[2]
    assert "port=8095" in cmd[2]
    assert "log_level='debug'" in cmd[2]
    assert cmd[3] == web.OPS_WEB_PROCESS_SENTINEL


def test_daemon_child_env_resets_pyinstaller_extraction(monkeypatch, packaged_runtime):
    monkeypatch.setenv("BLUEARCH_WEB_DAEMON_CHILD", "0")
    env = web._daemon_child_env()

    assert env["BLUEARCH_WEB_DAEMON_CHILD"] == "1"
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_daemon_cwd_uses_runtime_dir_for_packaged_child(monkeypatch, tmp_path, packaged_runtime):
    runtime_dir = tmp_path / ".bluearch"
    monkeypatch.setattr(web, "PID_DIR", os.fspath(runtime_dir))

    assert web._daemon_cwd() == os.fspath(runtime_dir)
    assert runtime_dir.is_dir()


def test_daemon_cwd_uses_source_api_dir_for_python_runtime(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(web.sys, "executable", sys.executable)

    assert web._daemon_cwd().endswith(os.path.join("src", "api"))


def test_find_cli_executable_uses_public_name_not_legacy_conflict(monkeypatch, tmp_path, packaged_runtime):
    public_launcher = tmp_path / "bluearch-aws-ops"
    public_launcher.write_text("#!/bin/sh\n")
    public_launcher.chmod(0o755)
    legacy_launcher = tmp_path / "bluearch"
    legacy_launcher.write_text("#!/bin/sh\n")
    legacy_launcher.chmod(0o755)

    bundled_python = tmp_path / "python"
    bundled_python.write_text("# not executable\n")
    bundled_python.chmod(0o644)

    monkeypatch.setattr(sys, "argv", ["bluearch"])
    monkeypatch.setattr(sys, "executable", str(bundled_python))
    monkeypatch.setattr(
        web.shutil,
        "which",
        lambda command: str(public_launcher) if command == "bluearch-aws-ops" else str(legacy_launcher) if command == "bluearch" else None,
    )

    assert web._find_cli_executable() == os.fspath(public_launcher)


def test_find_cli_executable_rejects_public_named_symlink_to_legacy_binary(monkeypatch, tmp_path, packaged_runtime):
    """Catches a public filename masking a legacy executable target."""
    legacy_launcher = tmp_path / "bluearch"
    legacy_launcher.write_text("#!/bin/sh\n")
    legacy_launcher.chmod(0o755)
    public_symlink = tmp_path / "bluearch-aws-ops"
    public_symlink.symlink_to(legacy_launcher)
    bundled_python = tmp_path / "python"
    bundled_python.write_text("# not executable\n")
    bundled_python.chmod(0o644)
    real_isfile = web.os.path.isfile

    monkeypatch.setattr(sys, "argv", [str(public_symlink)])
    monkeypatch.setattr(sys, "executable", str(bundled_python))
    monkeypatch.setattr(web.shutil, "which", lambda command: None)
    monkeypatch.setattr(
        web.os.path,
        "isfile",
        lambda path: real_isfile(path) if os.fspath(path).startswith(os.fspath(tmp_path)) else False,
    )

    assert web._find_cli_executable() is None


def test_find_cli_executable_never_selects_arbitrary_sys_executable(monkeypatch, tmp_path):
    """Catches fallback that spawns an unrelated executable as Ops."""
    arbitrary_executable = tmp_path / "custom-launcher"
    arbitrary_executable.write_text("#!/bin/sh\n")
    arbitrary_executable.chmod(0o755)
    real_isfile = web.os.path.isfile

    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "argv", ["not-bluearch-aws-ops"])
    monkeypatch.setattr(sys, "executable", str(arbitrary_executable))
    monkeypatch.setattr(web.shutil, "which", lambda command: None)
    monkeypatch.setattr(
        web.os.path,
        "isfile",
        lambda path: real_isfile(path) if os.fspath(path).startswith(os.fspath(tmp_path)) else False,
    )

    assert web._find_cli_executable() is None


def test_legacy_listener_is_reported_without_termination(monkeypatch, capsys):
    """Catches managed startup killing a legacy dashboard instead of flagging it."""
    terminated = []

    monkeypatch.setattr(web, "_read_pid_record", lambda: None)
    monkeypatch.setattr(web, "_listener_pids", lambda port: {4321})
    monkeypatch.setattr(
        web,
        "_process_snapshot",
        lambda pid: {
            "pid": pid,
            "create_time": 10.0,
            "cmdline": ("/usr/local/bin/bluearch", "web", "start"),
            "executable": "/usr/local/bin/bluearch",
        },
    )
    monkeypatch.setattr(web, "_terminate_process", lambda pid, created: terminated.append((pid, created)))
    monkeypatch.setattr(web, "_remove_stale_pid_files", lambda: None)

    web._stop_known_web_servers(8095)

    assert terminated == []
    assert "migration conflict" in capsys.readouterr().out.lower()


@pytest.mark.parametrize(
    "cmdline",
    [
        ("/opt/homebrew/bin/bluearch-aws-tags", "web", "start"),
        ("python", "-m", "uvicorn", "web.app:create_app"),
        ("uvicorn", "web.app:create_app"),
        ("/usr/local/bin/bluearch", "web", "start"),
    ],
)
def test_listener_discovery_never_signals_non_public_ops_process(monkeypatch, cmdline):
    terminated = []
    monkeypatch.setattr(web, "_read_pid_record", lambda: None)
    monkeypatch.setattr(web, "_listener_pids", lambda port: {9876})
    monkeypatch.setattr(
        web,
        "_process_snapshot",
        lambda pid: {"pid": pid, "create_time": 20.0, "cmdline": cmdline, "executable": cmdline[0]},
    )
    monkeypatch.setattr(web, "_terminate_process", lambda pid, created: terminated.append((pid, created)))
    monkeypatch.setattr(web, "_remove_stale_pid_files", lambda: None)

    web._stop_known_web_servers(8095)

    assert terminated == []


def test_listener_discovery_signals_exact_public_ops_process(monkeypatch):
    terminated = []
    monkeypatch.setattr(web, "_read_pid_record", lambda: None)
    monkeypatch.setattr(web, "_listener_pids", lambda port: {9876})
    monkeypatch.setattr(
        web,
        "_process_snapshot",
        lambda pid: {
            "pid": pid,
            "create_time": 20.0,
            "cmdline": ("/opt/homebrew/bin/bluearch-aws-ops", "web", "start", "--daemon"),
            "executable": "/opt/homebrew/bin/bluearch-aws-ops",
        },
    )
    monkeypatch.setattr(
        web,
        "_terminate_process",
        lambda pid, created: terminated.append((pid, created)) or True,
    )
    monkeypatch.setattr(web, "_remove_stale_pid_files", lambda: None)

    web._stop_known_web_servers(8095)

    assert terminated == [(9876, 20.0)]


def test_public_argv_with_legacy_executable_target_is_not_signaled(monkeypatch):
    snapshot = {
        "pid": 9876,
        "create_time": 20.0,
        "cmdline": ("/opt/homebrew/bin/bluearch-aws-ops", "web", "start"),
        "executable": "/opt/homebrew/Cellar/legacy/bluearch",
    }

    assert web._snapshot_is_public_ops_web(snapshot) is False


def test_terminate_rejects_reused_pid_before_signaling(monkeypatch):
    signals = []
    monkeypatch.setattr(
        web,
        "_process_snapshot",
        lambda pid: {
            "pid": pid,
            "create_time": 22.0,
            "cmdline": ("/opt/homebrew/bin/bluearch-aws-ops", "web", "start"),
            "executable": "/opt/homebrew/bin/bluearch-aws-ops",
        },
    )
    monkeypatch.setattr(web.os, "kill", lambda pid, sig: signals.append((pid, sig)))

    assert web._terminate_process(55, 11.0) is False
    assert signals == []


def test_pid_record_requires_stable_public_ops_identity(monkeypatch, tmp_path):
    pid_file = tmp_path / "web-server.pid"
    monkeypatch.setattr(web, "PID_DIR", str(tmp_path))
    monkeypatch.setattr(web, "PID_FILE", str(pid_file))
    monkeypatch.setattr(
        web,
        "_process_snapshot",
        lambda pid: {
            "pid": pid,
            "create_time": 123.5,
            "cmdline": ("/opt/homebrew/bin/bluearch-aws-ops", "web", "start"),
            "executable": "/opt/homebrew/bin/bluearch-aws-ops",
        },
    )

    web._write_pid(123)

    assert web._read_pid_record() == {
        "schema": web.PID_RECORD_SCHEMA,
        "pid": 123,
        "create_time": 123.5,
        "command": "bluearch-aws-ops",
    }


def test_daemon_child_skips_single_instance_guard(monkeypatch):
    started = {}

    monkeypatch.setenv("BLUEARCH_CORE_MANAGED_WEB_START", "1")
    monkeypatch.setenv("BLUEARCH_WEB_DAEMON_CHILD", "1")
    monkeypatch.setattr(web, "_is_server_running", lambda: True)
    monkeypatch.setattr(web, "_find_available_port", lambda host, port: port)
    monkeypatch.setattr(web, "_ensure_core_dependency", lambda: None)
    monkeypatch.setattr(
        web,
        "_start_foreground",
        lambda host, port, log_level, no_browser: started.update(
            {
                "host": host,
                "port": port,
                "log_level": log_level,
                "no_browser": no_browser,
            }
        ),
    )

    web.start(port=8099, host="127.0.0.1", daemon=False, log_level="info", no_browser=True)

    assert started == {
        "host": "127.0.0.1",
        "port": 8099,
        "log_level": "info",
        "no_browser": True,
    }


def test_web_start_requires_core_managed_start(monkeypatch):
    monkeypatch.delenv("BLUEARCH_CORE_MANAGED_WEB_START", raising=False)

    with pytest.raises(typer.Exit):
        web.start(port=8099, host="127.0.0.1", daemon=True, log_level="info", no_browser=True)


def test_fixed_sso_port_does_not_fallback(monkeypatch):
    called = {}

    monkeypatch.setattr(web, "_stop_known_web_servers", lambda port: called.setdefault("stopped", port))
    monkeypatch.setattr(web, "_is_port_available", lambda host, port: True)
    monkeypatch.setattr(
        web,
        "_find_available_port",
        lambda host, port: (_ for _ in ()).throw(AssertionError("should not fallback")),
    )

    assert web._resolve_start_port("127.0.0.1", 8095) == 8095
    assert called["stopped"] == 8095


def test_custom_port_keeps_auto_fallback(monkeypatch):
    monkeypatch.setattr(web, "_find_available_port", lambda host, port: 8123)
    assert web._resolve_start_port("127.0.0.1", 8120) == 8123
