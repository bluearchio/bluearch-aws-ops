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


def test_daemon_command_uses_cli_launcher_for_legacy_nuitka_runtime(monkeypatch, tmp_path):
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


def test_daemon_command_uses_cli_launcher_for_unique_nuitka_runtime(
    monkeypatch, tmp_path
):
    launcher = tmp_path / "bluearch-aws-ops"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)

    runtime_tmp = tmp_path / "runtime-tmp"
    runtime_dir = runtime_tmp / "bluearch-aws-ops_41001_1234567890_123456"
    runtime_dir.mkdir(parents=True)
    bundled_python = runtime_dir / "python"
    bundled_python.write_text("# internal runtime\n")
    bundled_python.chmod(0o755)

    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(web.tempfile, "gettempdir", lambda: str(runtime_tmp))
    monkeypatch.setattr(sys, "argv", [str(launcher)])
    monkeypatch.setattr(sys, "executable", str(bundled_python))
    monkeypatch.setattr(web.shutil, "which", lambda command: None)

    cmd = web._build_daemon_command("127.0.0.1", 8095, "info")

    assert cmd[0] == str(launcher)
    assert cmd[1:3] == ["web", "start"]


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
    monkeypatch.setattr(web, "_pid_file_present", lambda: False)
    monkeypatch.setattr(web, "_listener_pids", lambda port: {9876})
    monkeypatch.setattr(
        web,
        "_process_snapshot",
        lambda pid: {
            "pid": pid,
            "create_time": 20.0,
            "cmdline": (
                "/opt/homebrew/Cellar/bluearch-aws-ops/0.13.8/bin/bluearch-aws-ops",
                "web", "start", "--host", "127.0.0.1", "--port", "8095",
                "--log-level", "info", "--no-browser",
            ),
            "executable": "/opt/homebrew/Cellar/bluearch-aws-ops/0.13.8/bin/bluearch-aws-ops",
            "uid": os.getuid(),
            "ppid": 1,
        },
    )
    monkeypatch.setattr(web, "_is_strict_current_listener", lambda snapshot, port: True)
    monkeypatch.setattr(web, "_terminate_managed_runtime", lambda managed: terminated.append(managed) or [9876])
    monkeypatch.setattr(web, "_remove_stale_pid_files", lambda: None)

    web._stop_known_web_servers(8095)

    assert terminated[0]["listener"]["pid"] == 9876


def test_public_ops_identity_survives_homebrew_cleanup_of_old_cellar(tmp_path):
    deleted_binary = (
        tmp_path
        / "Cellar"
        / "bluearch-aws-ops"
        / "0.13.7"
        / "bin"
        / "bluearch-aws-ops"
    )
    assert not deleted_binary.exists()
    snapshot = {
        "pid": 9876,
        "create_time": 20.0,
        "cmdline": (
            str(deleted_binary), "web", "start", "--host", "127.0.0.1",
            "--port", "8095", "--log-level", "info", "--no-browser",
        ),
        "executable": str(deleted_binary),
        "uid": os.getuid(),
        "ppid": 1,
    }

    assert web._snapshot_is_public_ops_web(snapshot) is True


@pytest.mark.parametrize("argv_uses_runtime", [False, True])
def test_public_ops_identity_accepts_exact_unique_nuitka_listener(
    monkeypatch,
    tmp_path,
    argv_uses_runtime,
):
    runtime_tmp = tmp_path / "runtime-tmp"
    runtime = (
        runtime_tmp
        / "bluearch-aws-ops_41001_1234567890_123456"
        / "bluearch-aws-ops.bin"
    )
    runtime.parent.mkdir(parents=True)
    runtime.write_text("#!/bin/sh\n")
    runtime.chmod(0o755)
    launcher = tmp_path / "Cellar" / "bluearch-aws-ops" / "0.13.8" / "bin" / "bluearch-aws-ops"
    monkeypatch.setattr(web.tempfile, "gettempdir", lambda: str(runtime_tmp))
    snapshot = {
        "pid": 41002,
        "ppid": 41001,
        "uid": os.getuid(),
        "create_time": 20.0,
        "cmdline": (
            str(runtime if argv_uses_runtime else launcher),
            "web", "start", "--host", "127.0.0.1", "--port", "8095",
            "--log-level", "info", "--no-browser",
        ),
        "executable": str(runtime),
    }

    assert web._snapshot_is_public_ops_web(snapshot) is True


@pytest.mark.parametrize(
    "runtime_directory",
    [
        "bluearch-aws-ops_49999_1234567890_123456",
        "bluearch-aws-ops_41001_not-a-time_123456",
        "bluearch-aws-ops-41001-1234567890-123456",
        "bluearch-aws-ops_41001_1234567890_1000000",
        "bluearch-aws-ops_41001_1234567890_123456_extra",
    ],
)
def test_public_ops_identity_rejects_unexpected_unique_nuitka_runtime(
    monkeypatch,
    tmp_path,
    runtime_directory,
):
    runtime_tmp = tmp_path / "runtime-tmp"
    runtime = runtime_tmp / runtime_directory / "bluearch-aws-ops.bin"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("#!/bin/sh\n")
    runtime.chmod(0o755)
    monkeypatch.setattr(web.tempfile, "gettempdir", lambda: str(runtime_tmp))
    snapshot = {
        "pid": 41002,
        "ppid": 41001,
        "uid": os.getuid(),
        "cmdline": (str(runtime), "web", "start"),
        "executable": str(runtime),
    }

    assert web._snapshot_is_public_ops_web(snapshot) is False


def test_public_ops_identity_rejects_symlinked_unique_nuitka_runtime(
    monkeypatch, tmp_path
):
    runtime_tmp = tmp_path / "runtime-tmp"
    runtime = (
        runtime_tmp
        / "bluearch-aws-ops_41001_1234567890_123456"
        / "bluearch-aws-ops.bin"
    )
    target = tmp_path / "foreign.bin"
    target.write_text("#!/bin/sh\n")
    target.chmod(0o755)
    runtime.parent.mkdir(parents=True)
    runtime.symlink_to(target)
    monkeypatch.setattr(web.tempfile, "gettempdir", lambda: str(runtime_tmp))
    snapshot = {
        "pid": 41002,
        "ppid": 41001,
        "uid": os.getuid(),
        "cmdline": (str(runtime), "web", "start"),
        "executable": str(runtime),
    }

    assert web._snapshot_is_public_ops_web(snapshot) is False


def test_public_ops_identity_rejects_foreign_uid_nuitka_runtime(
    monkeypatch, tmp_path
):
    runtime_tmp = tmp_path / "runtime-tmp"
    runtime = (
        runtime_tmp
        / "bluearch-aws-ops_41001_1234567890_123456"
        / "bluearch-aws-ops.bin"
    )
    runtime.parent.mkdir(parents=True)
    runtime.write_text("#!/bin/sh\n")
    runtime.chmod(0o755)
    monkeypatch.setattr(web.tempfile, "gettempdir", lambda: str(runtime_tmp))
    snapshot = {
        "pid": 41002,
        "ppid": 41001,
        "uid": os.getuid() + 1,
        "cmdline": (str(runtime), "web", "start"),
        "executable": str(runtime),
    }

    assert web._snapshot_is_public_ops_web(snapshot) is False


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
    launcher = tmp_path / "bluearch-aws-ops"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)
    monkeypatch.setattr(web, "PID_DIR", str(tmp_path))
    monkeypatch.setattr(web, "PID_FILE", str(pid_file))
    snapshot = {
        "pid": 123,
        "create_time": 123.5,
        "cmdline": (
            str(launcher), "web", "start", "--host", "127.0.0.1",
            "--port", "8095", "--log-level", "info", "--no-browser",
        ),
        "executable": str(launcher),
        "uid": os.getuid(),
        "ppid": 1,
    }
    monkeypatch.setattr(web, "_process_snapshot", lambda pid: snapshot)

    web._write_pid(123)

    assert web._read_pid_record() == {
        "schema": web.PID_RECORD_SCHEMA,
        "product": web.PID_RECORD_PRODUCT,
        "command": "bluearch-aws-ops",
        "listener": web._identity_from_snapshot(snapshot),
        "supervisor": None,
    }


def test_legacy_supervisor_record_migrates_to_listener_and_supervisor_identities(
    monkeypatch, tmp_path
):
    """The 0.13.7 record survives Cellar cleanup and binds the real listener."""
    state_dir = tmp_path / "runtime-state"
    state_dir.mkdir(mode=0o700)
    pid_file = state_dir / "web-server.pid"
    monkeypatch.setattr(web, "PID_DIR", str(state_dir))
    monkeypatch.setattr(web, "PID_FILE", str(pid_file))
    monkeypatch.setenv("HOME", str(tmp_path))

    deleted_launcher = (
        tmp_path / "Cellar" / "bluearch-aws-ops" / "0.13.7" / "bin" / "bluearch-aws-ops"
    )
    runtime = tmp_path / ".bluearch-aws-ops" / "bin" / "bluearch-aws-ops.bin"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("#!/bin/sh\n")
    runtime.chmod(0o755)
    argv = (
        str(deleted_launcher), "web", "start", "--host", "127.0.0.1",
        "--port", "8095", "--log-level", "info", "--no-browser",
    )
    supervisor = {
        "pid": 41001,
        "create_time": 100.0,
        "cmdline": argv,
        "executable": str(deleted_launcher),
        "uid": os.getuid(),
        "ppid": 1,
    }
    listener = {
        "pid": 41002,
        "create_time": 101.0,
        "cmdline": argv,
        "executable": str(runtime),
        "uid": os.getuid(),
        "ppid": supervisor["pid"],
    }
    pid_file.write_text(
        '{"command":"bluearch-aws-ops","create_time":100.0,"pid":41001,"schema":1}\n'
    )
    pid_file.chmod(0o600)

    snapshots = {supervisor["pid"]: supervisor, listener["pid"]: listener}
    monkeypatch.setattr(web, "_process_snapshot", lambda pid: snapshots.get(pid))
    monkeypatch.setattr(web, "_listener_pids", lambda port: {listener["pid"]} if port == 8095 else set())
    monkeypatch.setattr(web, "_probe_ops_health", lambda port: port == 8095)
    monkeypatch.setattr(web, "_recaptured_snapshot_matches", lambda snapshot: True)

    managed = web._managed_runtime_from_record(
        web._read_pid_record(), target_port=8095, listener_pids={listener["pid"]}
    )

    assert managed["listener"]["pid"] == listener["pid"]
    assert managed["supervisor"]["pid"] == supervisor["pid"]
    migrated = web._read_pid_record()
    assert migrated["schema"] == web.PID_RECORD_SCHEMA
    assert migrated["listener"]["pid"] == listener["pid"]
    assert migrated["supervisor"]["pid"] == supervisor["pid"]
    assert (pid_file.stat().st_mode & 0o777) == 0o600


def test_packaged_spawn_resolves_unique_nuitka_listener_child(monkeypatch, tmp_path):
    runtime_tmp = tmp_path / "runtime-tmp"
    runtime = (
        runtime_tmp
        / "bluearch-aws-ops_51001_1234567890_123456"
        / "bluearch-aws-ops.bin"
    )
    runtime.parent.mkdir(parents=True)
    runtime.write_text("#!/bin/sh\n")
    runtime.chmod(0o755)
    launcher = tmp_path / "Cellar" / "bluearch-aws-ops" / "0.13.8" / "bin" / "bluearch-aws-ops"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)
    argv = (
        str(launcher), "web", "start", "--host", "127.0.0.1",
        "--port", "8095", "--log-level", "info", "--no-browser",
    )
    supervisor = {
        "pid": 51001,
        "create_time": 200.0,
        "cmdline": argv,
        "executable": str(launcher),
        "uid": os.getuid(),
        "ppid": 1,
    }
    listener = {
        "pid": 51002,
        "create_time": 201.0,
        "cmdline": argv,
        "executable": str(runtime),
        "uid": os.getuid(),
        "ppid": supervisor["pid"],
    }
    snapshots = {supervisor["pid"]: supervisor, listener["pid"]: listener}
    monkeypatch.setattr(web.tempfile, "gettempdir", lambda: str(runtime_tmp))
    monkeypatch.setattr(web, "_process_snapshot", lambda pid: snapshots.get(pid))
    monkeypatch.setattr(web, "_listener_pids", lambda port: {listener["pid"]})
    monkeypatch.setattr(web, "_probe_ops_health", lambda port: True)
    monkeypatch.setattr(web, "_recaptured_snapshot_matches", lambda snapshot: True)

    managed = web._resolve_spawned_daemon_runtime(supervisor, 8095)

    assert managed["listener"] == listener
    assert managed["supervisor"] == supervisor


def test_failed_spawn_recovers_reparented_unique_listener_without_health(
    monkeypatch, tmp_path
):
    runtime_tmp = tmp_path / "runtime-tmp"
    runtime = (
        runtime_tmp
        / "bluearch-aws-ops_52001_1234567890_123456"
        / "bluearch-aws-ops.bin"
    )
    runtime.parent.mkdir(parents=True)
    runtime.write_text("#!/bin/sh\n")
    runtime.chmod(0o755)
    launcher = tmp_path / "Cellar" / "bluearch-aws-ops" / "0.13.8" / "bin" / "bluearch-aws-ops"
    argv = (
        str(launcher), "web", "start", "--host", "127.0.0.1",
        "--port", "8095", "--log-level", "info", "--no-browser",
    )
    spawned = {
        "pid": 52001,
        "create_time": 210.0,
        "cmdline": argv,
        "executable": str(launcher),
        "uid": os.getuid(),
        "ppid": 1,
    }
    orphan = {
        "pid": 52002,
        "create_time": 211.0,
        "cmdline": argv,
        "executable": str(runtime),
        "uid": os.getuid(),
        "ppid": 1,
    }
    monkeypatch.setattr(web.tempfile, "gettempdir", lambda: str(runtime_tmp))
    monkeypatch.setattr(
        web,
        "_process_snapshot",
        lambda pid: orphan if pid == orphan["pid"] else None,
    )
    monkeypatch.setattr(web, "_listener_pids", lambda port: {orphan["pid"]})
    monkeypatch.setattr(web, "_recaptured_snapshot_matches", lambda snapshot: True)
    monkeypatch.setattr(
        web,
        "_probe_ops_health",
        lambda port: (_ for _ in ()).throw(AssertionError("failure cleanup must not require health")),
    )

    managed = web._captured_runtime_for_spawned(spawned, 8095, require_health=False)

    assert managed["listener"] == orphan
    assert managed["supervisor"] is None


def test_wait_failure_uses_verified_runtime_cleanup_not_supervisor_only(monkeypatch):
    class FailedProcess:
        def poll(self):
            return 1

    spawned = {"pid": 53001}
    cleaned = []
    monkeypatch.setattr(web, "_cleanup_spawned_runtime", lambda snapshot, port: cleaned.append((snapshot, port)))
    monkeypatch.setattr(
        web,
        "_terminate_child_process",
        lambda proc: (_ for _ in ()).throw(AssertionError("supervisor-first fallback forbidden")),
    )

    with pytest.raises(typer.Exit):
        web._wait_for_daemon_ready(
            FailedProcess(),
            "127.0.0.1",
            8095,
            "/tmp/web.log",
            expected_snapshot=spawned,
        )

    assert cleaned == [(spawned, 8095)]


def test_managed_runtime_signals_listener_before_supervisor(monkeypatch):
    listener = {
        "pid": 61002,
        "create_time": 301.0,
        "cmdline": ("/tmp/bluearch-aws-ops.bin", "web", "start"),
        "executable": "/tmp/bluearch-aws-ops.bin",
        "uid": os.getuid(),
        "ppid": 61001,
    }
    supervisor = {
        "pid": 61001,
        "create_time": 300.0,
        "cmdline": listener["cmdline"],
        "executable": "/tmp/bluearch-aws-ops",
        "uid": os.getuid(),
        "ppid": 1,
    }
    calls = []

    def terminate(pid, created, **kwargs):
        calls.append((pid, kwargs["expected_identity"]))
        return True

    monkeypatch.setattr(web, "_terminate_process", terminate)
    monkeypatch.setattr(web, "_process_snapshot", lambda pid: supervisor)

    stopped = web._terminate_managed_runtime(
        {
            "listener": listener,
            "listener_identity": web._identity_from_snapshot(listener),
            "supervisor": supervisor,
        }
    )

    assert [pid for pid, _ in calls] == [listener["pid"], supervisor["pid"]]
    assert stopped == [listener["pid"], supervisor["pid"]]


def test_managed_runtime_reports_incomplete_when_original_supervisor_survives(monkeypatch):
    listener = {
        "pid": 61502,
        "create_time": 311.0,
        "cmdline": ("/tmp/bluearch-aws-ops.bin", "web", "start"),
        "executable": "/tmp/bluearch-aws-ops.bin",
        "uid": os.getuid(),
        "ppid": 61501,
    }
    supervisor = {
        "pid": 61501,
        "create_time": 310.0,
        "cmdline": listener["cmdline"],
        "executable": "/tmp/bluearch-aws-ops",
        "uid": os.getuid(),
        "ppid": 1,
    }
    calls = []

    def terminate(pid, created, **kwargs):
        calls.append(pid)
        return pid == listener["pid"]

    monkeypatch.setattr(web, "_terminate_process", terminate)
    monkeypatch.setattr(web, "_process_snapshot", lambda pid: supervisor)

    result = web._terminate_managed_runtime(
        {
            "listener": listener,
            "listener_identity": web._identity_from_snapshot(listener),
            "supervisor": supervisor,
        }
    )

    assert result is None
    assert calls == [listener["pid"], supervisor["pid"]]


def test_stop_preserves_record_when_verified_supervisor_survives(monkeypatch):
    managed = {"listener": {"pid": 61602}}
    removed = []
    monkeypatch.setattr(web, "_read_pid_record", lambda: {"schema": web.PID_RECORD_SCHEMA})
    monkeypatch.setattr(web, "_managed_runtime_from_record", lambda record: managed)
    monkeypatch.setattr(web, "_terminate_managed_runtime", lambda runtime: None)
    monkeypatch.setattr(web, "_remove_pid", lambda: removed.append(True))

    with pytest.raises(typer.Exit):
        web.stop()

    assert removed == []


def test_unverified_supervisor_fallback_waits_beyond_five_seconds_before_sigkill(
    monkeypatch
):
    snapshot = {
        "pid": 61701,
        "create_time": 320.0,
        "cmdline": (
            "/tmp/bluearch-aws-ops", "web", "start", "--host", "127.0.0.1",
            "--port", "8095", "--log-level", "info", "--no-browser",
        ),
        "executable": "/tmp/bluearch-aws-ops",
        "uid": os.getuid(),
        "ppid": 1,
    }
    elapsed = [0.0]
    signals = []
    monkeypatch.setattr(web, "_snapshot_is_public_ops_web", lambda value: True)
    monkeypatch.setattr(web, "_recaptured_snapshot_matches", lambda value: True)
    monkeypatch.setattr(web, "_process_snapshot", lambda pid: snapshot)
    monkeypatch.setattr(
        web.time,
        "sleep",
        lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
    )
    monkeypatch.setattr(
        web.os,
        "kill",
        lambda pid, sig: signals.append((sig, elapsed[0])),
    )

    web._terminate_process(
        snapshot["pid"],
        snapshot["create_time"],
        expected_snapshot=snapshot,
        expected_identity=web._identity_from_snapshot(snapshot),
        grace_seconds=web.UNVERIFIED_NUITKA_SUPERVISOR_GRACE_SECONDS,
    )

    sigkill_times = [when for sig, when in signals if sig == web.signal.SIGKILL]
    assert sigkill_times and sigkill_times[0] > 5.0


def test_unclassified_popen_waits_beyond_nuitka_grace_before_kill():
    class SlowProcess:
        def __init__(self):
            self.wait_timeouts = []
            self.killed = False

        def poll(self):
            return None

        def terminate(self):
            return None

        def wait(self, timeout):
            self.wait_timeouts.append(timeout)
            if len(self.wait_timeouts) == 1:
                raise web.subprocess.TimeoutExpired("ops", timeout)

        def kill(self):
            self.killed = True

    proc = SlowProcess()

    web._terminate_child_process(proc)

    assert proc.killed is True
    assert proc.wait_timeouts[0] > 5.0


def test_terminate_treats_child_exit_during_grace_as_success_without_sigkill(monkeypatch):
    snapshot = {
        "pid": 62002,
        "create_time": 400.0,
        "cmdline": (
            "/tmp/bluearch-aws-ops", "web", "start", "--host", "127.0.0.1",
            "--port", "8095", "--log-level", "info", "--no-browser",
        ),
        "executable": "/tmp/bluearch-aws-ops",
        "uid": os.getuid(),
        "ppid": 62001,
    }
    signals = []
    monkeypatch.setattr(web, "_snapshot_is_public_ops_web", lambda value: True)
    monkeypatch.setattr(web, "_recaptured_snapshot_matches", lambda value: True)
    monkeypatch.setattr(web, "_process_snapshot", lambda pid: None)
    monkeypatch.setattr(web, "_process_is_gone_or_zombie", lambda pid: True)
    monkeypatch.setattr(web.os, "kill", lambda pid, sig: signals.append((pid, sig)))

    assert web._terminate_process(
        snapshot["pid"],
        snapshot["create_time"],
        expected_snapshot=snapshot,
        expected_identity=web._identity_from_snapshot(snapshot),
    ) is True
    assert signals == [(snapshot["pid"], web.signal.SIGTERM)]


def test_schema2_supervisor_pid_reuse_is_never_selected(monkeypatch):
    listener = {
        "pid": 63002,
        "create_time": 501.0,
        "cmdline": ("/tmp/bluearch-aws-ops", "web", "start"),
        "executable": "/tmp/bluearch-aws-ops",
        "uid": os.getuid(),
        "ppid": 63001,
    }
    supervisor = {
        "pid": 63001,
        "create_time": 500.0,
        "cmdline": listener["cmdline"],
        "executable": "/tmp/bluearch-aws-ops",
        "uid": os.getuid(),
        "ppid": 1,
    }
    reused = dict(supervisor, create_time=999.0, cmdline=("/usr/bin/sleep", "60"))
    record = {
        "schema": web.PID_RECORD_SCHEMA,
        "product": web.PID_RECORD_PRODUCT,
        "command": web.PUBLIC_OPS_EXECUTABLE,
        "listener": web._identity_from_snapshot(listener),
        "supervisor": web._identity_from_snapshot(supervisor),
    }
    monkeypatch.setattr(
        web,
        "_process_snapshot",
        lambda pid: listener if pid == listener["pid"] else reused,
    )
    monkeypatch.setattr(web, "_snapshot_is_public_ops_web", lambda snapshot: snapshot is listener)

    managed = web._managed_runtime_from_record(record)

    assert managed["listener"] is listener
    assert managed["supervisor"] is None


def test_schema2_supervisor_identity_survives_expected_daemon_reparent(monkeypatch):
    supervisor_at_start = {
        "pid": 64001,
        "create_time": 600.0,
        "cmdline": ("/tmp/bluearch-aws-ops", "web", "start"),
        "executable": "/tmp/bluearch-aws-ops",
        "uid": os.getuid(),
        "ppid": 63999,
    }
    listener = {
        "pid": 64002,
        "create_time": 601.0,
        "cmdline": supervisor_at_start["cmdline"],
        "executable": "/tmp/bluearch-aws-ops.bin",
        "uid": os.getuid(),
        "ppid": supervisor_at_start["pid"],
    }
    reparented_supervisor = dict(supervisor_at_start, ppid=1)
    record = {
        "schema": web.PID_RECORD_SCHEMA,
        "product": web.PID_RECORD_PRODUCT,
        "command": web.PUBLIC_OPS_EXECUTABLE,
        "listener": web._identity_from_snapshot(listener),
        "supervisor": web._identity_from_snapshot(supervisor_at_start),
    }
    monkeypatch.setattr(
        web,
        "_process_snapshot",
        lambda pid: listener if pid == listener["pid"] else reparented_supervisor,
    )
    monkeypatch.setattr(web, "_snapshot_is_public_ops_web", lambda snapshot: True)

    managed = web._managed_runtime_from_record(record)

    assert managed["supervisor"] == reparented_supervisor


def test_symlinked_pid_record_blocks_listener_cleanup(monkeypatch, tmp_path):
    target = tmp_path / "foreign.json"
    target.write_text(
        '{"command":"bluearch-aws-ops","create_time":1.0,"pid":123,"schema":1}\n'
    )
    link = tmp_path / "web-server.pid"
    link.symlink_to(target)
    monkeypatch.setattr(web, "PID_FILE", str(link))
    monkeypatch.setattr(web, "_listener_pids", lambda port: {9876})
    monkeypatch.setattr(
        web,
        "_terminate_managed_runtime",
        lambda managed: (_ for _ in ()).throw(AssertionError("must not signal")),
    )

    web._stop_known_web_servers(8095)

    assert web._read_pid_record() is None


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
