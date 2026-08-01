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

    runtime_dir = tmp_path / ".bluearch" / "bin"
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
