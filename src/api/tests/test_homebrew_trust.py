from types import SimpleNamespace

import pytest

from cli import config


def _make_formula_layout(tmp_path, version="0.2.6"):
    homebrew = tmp_path / "homebrew"
    brew = homebrew / "bin" / "brew"
    cellar = homebrew / "Cellar"
    prefix = cellar / "bluearch-aws-core" / version
    core = prefix / "bin" / "bluearch-aws-core"
    ops_prefix = cellar / "bluearch-aws-ops" / "0.13.9"
    ops = ops_prefix / "bin" / "bluearch-aws-ops"
    brew.parent.mkdir(parents=True)
    core.parent.mkdir(parents=True)
    ops.parent.mkdir(parents=True)
    brew.write_text("#!/bin/sh\n", encoding="utf-8")
    core.write_text("#!/bin/sh\n", encoding="utf-8")
    ops.write_text("#!/bin/sh\n", encoding="utf-8")
    brew.chmod(0o755)
    core.chmod(0o755)
    ops.chmod(0o755)
    return brew.resolve(), cellar.resolve(), prefix.resolve(), core.resolve()


def _homebrew_update_runner(
    commands,
    *,
    brew,
    cellar,
    prefix,
    core,
    core_output="bluearch-aws-core 0.2.6\n",
    core_returncode=0,
    prefix_output=None,
    prefix_returncode=0,
    ops_prefix=None,
    ops_prefix_output=None,
    ops_prefix_returncode=0,
):
    ops_prefix = ops_prefix or cellar / config.OPS_FORMULA_NAME / "0.13.9"

    def run(command, **kwargs):
        commands.append((command, kwargs))
        if command == [str(brew), "--prefix", config.CORE_FORMULA]:
            stdout = f"{prefix}\n" if prefix_output is None else prefix_output
            return SimpleNamespace(returncode=prefix_returncode, stdout=stdout, stderr="")
        if command == [str(brew), "--prefix", config.OPS_FORMULA]:
            stdout = f"{ops_prefix}\n" if ops_prefix_output is None else ops_prefix_output
            return SimpleNamespace(
                returncode=ops_prefix_returncode,
                stdout=stdout,
                stderr="",
            )
        if command == [str(brew), "--cellar"]:
            return SimpleNamespace(returncode=0, stdout=f"{cellar}\n", stderr="")
        if command == [str(core), "--version"]:
            return SimpleNamespace(returncode=core_returncode, stdout=core_output, stderr="")
        is_core_list = command == [
            str(brew),
            "list",
            "--versions",
            "bluearch-aws-core",
        ]
        stdout = "bluearch-aws-core 0.2.6\n" if is_core_list else ""
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    return run


def test_formula_trust_is_exact_and_formula_scoped(monkeypatch, tmp_path):
    brew, _, _, _ = _make_formula_layout(tmp_path)
    commands = []
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew))
    monkeypatch.setattr(
        config.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0),
    )

    assert config._trust_homebrew_formula(config.CORE_FORMULA)
    assert config._trust_homebrew_formula(config.OPS_FORMULA)
    assert commands == [
        [str(brew), "trust", "--formula", "bluearchio/tap/bluearch-aws-core"],
        [str(brew), "trust", "--formula", "bluearchio/tap/bluearch-aws-ops"],
    ]


def test_active_homebrew_mutation_trusts_before_install(monkeypatch, tmp_path):
    brew, _, _, _ = _make_formula_layout(tmp_path)
    commands = []
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew))
    monkeypatch.setattr(
        config.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0),
    )

    assert config._run_trusted_homebrew_formula("install", config.CORE_FORMULA)
    assert commands == [
        [str(brew), "trust", "--formula", "bluearchio/tap/bluearch-aws-core"],
        [str(brew), "install", "bluearchio/tap/bluearch-aws-core"],
    ]


def test_ops_homebrew_mutation_trusts_core_then_ops(monkeypatch, tmp_path):
    brew, _, _, _ = _make_formula_layout(tmp_path)
    commands = []
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew))
    monkeypatch.setattr(
        config.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0),
    )

    assert config._run_trusted_homebrew_formula("upgrade", config.OPS_FORMULA)
    assert commands == [
        [str(brew), "trust", "--formula", config.CORE_FORMULA],
        [str(brew), "trust", "--formula", config.OPS_FORMULA],
        [str(brew), "upgrade", config.OPS_FORMULA],
    ]


def test_active_homebrew_mutation_rejects_unapproved_formula(monkeypatch):
    commands = []
    monkeypatch.setattr(config.subprocess, "run", lambda command, **kwargs: commands.append(command))

    try:
        config._run_trusted_homebrew_formula("install", "third-party/tap/wrapper")
    except ValueError:
        pass
    else:
        raise AssertionError("unapproved formula should be rejected")

    assert commands == []


def test_outdated_check_trusts_and_queries_only_the_exact_ops_formula(monkeypatch, tmp_path):
    brew, _, _, _ = _make_formula_layout(tmp_path)
    commands = []
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew))

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(config.subprocess, "run", run)

    result = config._run_trusted_homebrew_outdated()

    assert result.returncode == 0
    assert commands == [
        [str(brew), "trust", "--formula", "bluearchio/tap/bluearch-aws-core"],
        [str(brew), "trust", "--formula", "bluearchio/tap/bluearch-aws-ops"],
        [str(brew), "outdated", "bluearchio/tap/bluearch-aws-ops"],
    ]


def test_outdated_check_treats_nonzero_as_failure(monkeypatch, tmp_path):
    brew, _, _, _ = _make_formula_layout(tmp_path)
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew))
    responses = iter(
        [
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=2, stdout="", stderr="tap unavailable"),
        ]
    )
    monkeypatch.setattr(config.subprocess, "run", lambda command, **kwargs: next(responses))

    with pytest.raises(RuntimeError, match="tap unavailable"):
        config._run_trusted_homebrew_outdated()


def test_homebrew_update_trusts_both_formulas_and_verifies_formula_core_before_ops(
    monkeypatch, tmp_path
):
    brew, cellar, prefix, core = _make_formula_layout(tmp_path)
    ops_prefix = cellar / config.OPS_FORMULA_NAME / "0.13.9"
    ops = (ops_prefix / "bin" / config.PUBLIC_OPS_EXECUTABLE).resolve()
    commands = []
    fake_override = tmp_path / "fake" / "bluearch-aws-core"
    fake_ops = tmp_path / "fake" / "bluearch-aws-ops"
    fake_ops.parent.mkdir()
    fake_ops.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_ops.chmod(0o755)
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", str(fake_override))
    monkeypatch.setenv("BLUEARCH_CORE_BLUEARCH_CMD", str(fake_ops))
    monkeypatch.setenv("PATH", str(fake_ops.parent))
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew) if name == "brew" else None)
    monkeypatch.setattr(
        config.subprocess,
        "run",
        _homebrew_update_runner(
            commands, brew=brew, cellar=cellar, prefix=prefix, core=core
        ),
    )

    assert config._perform_homebrew_update("0.2.6") is True
    assert [command for command, _ in commands] == [
        [str(brew), "trust", "--formula", config.CORE_FORMULA],
        [str(brew), "trust", "--formula", config.OPS_FORMULA],
        [str(brew), "update"],
        [str(brew), "list", "--versions", "bluearch-aws-core"],
        [str(brew), "trust", "--formula", config.CORE_FORMULA],
        [str(brew), "upgrade", config.CORE_FORMULA],
        [str(brew), "--prefix", config.CORE_FORMULA],
        [str(brew), "--cellar"],
        [str(core), "--version"],
        [str(brew), "trust", "--formula", config.CORE_FORMULA],
        [str(brew), "trust", "--formula", config.OPS_FORMULA],
        [str(brew), "upgrade", config.OPS_FORMULA],
        [str(brew), "--prefix", config.CORE_FORMULA],
        [str(brew), "--cellar"],
        [str(brew), "--prefix", config.OPS_FORMULA],
        [str(brew), "--cellar"],
        [
            str(core),
            "start",
            "--daemon",
            "--web-apps",
            "bluearch-aws-ops",
        ],
    ]
    core_kwargs = next(kwargs for command, kwargs in commands if command == [str(core), "--version"])
    assert "BLUEARCH_CORE_BINARY" not in core_kwargs["env"]
    restart_kwargs = next(
        kwargs
        for command, kwargs in commands
        if command
        == [
            str(core),
            "start",
            "--daemon",
            "--web-apps",
            "bluearch-aws-ops",
        ]
    )
    assert "BLUEARCH_CORE_BINARY" not in restart_kwargs["env"]
    assert "BLUEARCH_MINIMUM_CORE_VERSION" not in restart_kwargs["env"]
    assert restart_kwargs["env"]["BLUEARCH_CORE_BLUEARCH_CMD"] == str(ops)
    assert [str(fake_ops)] not in [command for command, _ in commands]
    ops_prefix_kwargs = next(
        kwargs
        for command, kwargs in commands
        if command == [str(brew), "--prefix", config.OPS_FORMULA]
    )
    assert "BLUEARCH_CORE_BLUEARCH_CMD" not in ops_prefix_kwargs["env"]


def test_homebrew_update_fails_when_public_core_runtime_cannot_restart(monkeypatch, tmp_path):
    brew, cellar, prefix, core = _make_formula_layout(tmp_path)
    commands = []
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew) if name == "brew" else None)
    base_runner = _homebrew_update_runner(
        commands, brew=brew, cellar=cellar, prefix=prefix, core=core
    )

    def run(command, **kwargs):
        result = base_runner(command, **kwargs)
        if command == [
            str(core),
            "start",
            "--daemon",
            "--web-apps",
            "bluearch-aws-ops",
        ]:
            return SimpleNamespace(returncode=1, stdout="", stderr="runtime conflict")
        return result

    monkeypatch.setattr(config.subprocess, "run", run)

    assert config._perform_homebrew_update("0.2.6") is False
    assert [
        str(core),
        "start",
        "--daemon",
        "--web-apps",
        "bluearch-aws-ops",
    ] in [command for command, _ in commands]


def test_homebrew_update_pins_one_canonical_brew_when_path_is_retargeted(
    monkeypatch, tmp_path
):
    brew, cellar, prefix, core = _make_formula_layout(tmp_path)
    replacement = tmp_path / "replacement" / "bin" / "brew"
    replacement.parent.mkdir(parents=True)
    replacement.write_text("#!/bin/sh\n", encoding="utf-8")
    replacement.chmod(0o755)
    replacement = replacement.resolve()
    which_calls = []
    commands = []

    def which(name):
        which_calls.append(name)
        return str(brew) if len(which_calls) == 1 else str(replacement)

    base_runner = _homebrew_update_runner(
        commands, brew=brew, cellar=cellar, prefix=prefix, core=core
    )

    def retargeting_runner(command, **kwargs):
        monkeypatch.setenv("PATH", str(replacement.parent))
        return base_runner(command, **kwargs)

    monkeypatch.setattr(config.shutil, "which", which)
    monkeypatch.setattr(config.subprocess, "run", retargeting_runner)

    assert config._perform_homebrew_update("0.2.6") is True
    assert which_calls == ["brew"]
    executed = [command for command, _ in commands]
    assert all(command[0] in {str(brew), str(core)} for command in executed)
    assert all(command[0] != str(replacement) for command in executed)


def test_homebrew_workflows_fail_closed_without_canonical_brew(monkeypatch):
    commands = []
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        config.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0),
    )

    assert config._trust_homebrew_formula(config.CORE_FORMULA) is False
    assert config._run_trusted_homebrew_formula("install", config.CORE_FORMULA) is False
    assert config._perform_homebrew_update("0.2.6") is False
    with pytest.raises(RuntimeError, match="resolve the Homebrew executable"):
        config._run_trusted_homebrew_outdated()
    assert commands == []


def test_homebrew_update_stops_when_brew_update_fails(monkeypatch, tmp_path):
    brew, _, _, _ = _make_formula_layout(tmp_path)
    commands = []
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew))

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(
            returncode=2 if command == [str(brew), "update"] else 0,
            stdout="",
            stderr="network unavailable",
        )

    monkeypatch.setattr(config.subprocess, "run", run)

    assert config._perform_homebrew_update("0.2.6") is False
    assert commands == [
        [str(brew), "trust", "--formula", config.CORE_FORMULA],
        [str(brew), "trust", "--formula", config.OPS_FORMULA],
        [str(brew), "update"],
    ]


@pytest.mark.parametrize(
    ("core_output", "core_returncode"),
    [
        ("bluearch-core 9.9.9\n", 0),
        ("bluearch-aws-core 0.2.5\n", 0),
        ("bluearch-aws-core 99.99.99\nunexpected output\n", 0),
        ("bluearch-aws-core 99.99.99\n", 1),
    ],
)
def test_homebrew_update_blocks_ops_upgrade_for_invalid_or_old_core(
    monkeypatch, tmp_path, core_output, core_returncode
):
    brew, cellar, prefix, core = _make_formula_layout(tmp_path)
    commands = []
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_core = fake_bin / "bluearch-aws-core"
    fake_core.write_text("#!/bin/sh\necho 'bluearch-aws-core 99.99.99'\n", encoding="utf-8")
    fake_core.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", str(fake_core))
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew) if name == "brew" else None)
    monkeypatch.setattr(
        config.subprocess,
        "run",
        _homebrew_update_runner(
            commands,
            brew=brew,
            cellar=cellar,
            prefix=prefix,
            core=core,
            core_output=core_output,
            core_returncode=core_returncode,
        ),
    )

    assert config._perform_homebrew_update("0.2.6") is False
    executed = [command for command, _ in commands]
    assert [str(core), "--version"] in executed
    assert [str(fake_core), "--version"] not in executed
    assert [str(brew), "upgrade", config.OPS_FORMULA] not in executed


@pytest.mark.parametrize(
    ("prefix_output", "prefix_returncode"),
    [
        ("relative/formula-prefix\n", 0),
        ("/first/prefix\n/second/prefix\n", 0),
        ("", 1),
    ],
)
def test_homebrew_update_blocks_ops_for_malformed_or_failed_formula_prefix(
    monkeypatch, tmp_path, prefix_output, prefix_returncode
):
    brew, cellar, prefix, core = _make_formula_layout(tmp_path)
    commands = []
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew) if name == "brew" else None)
    monkeypatch.setattr(
        config.subprocess,
        "run",
        _homebrew_update_runner(
            commands,
            brew=brew,
            cellar=cellar,
            prefix=prefix,
            core=core,
            prefix_output=prefix_output,
            prefix_returncode=prefix_returncode,
        ),
    )

    assert config._perform_homebrew_update("0.2.6") is False
    executed = [command for command, _ in commands]
    assert [str(core), "--version"] not in executed
    assert [str(brew), "upgrade", config.OPS_FORMULA] not in executed


def test_homebrew_update_blocks_core_binary_that_escapes_formula_prefix(monkeypatch, tmp_path):
    brew, cellar, prefix, core = _make_formula_layout(tmp_path)
    outside = tmp_path / "outside" / "bluearch-aws-core"
    outside.parent.mkdir()
    outside.write_text("#!/bin/sh\n", encoding="utf-8")
    outside.chmod(0o755)
    core.unlink()
    core.symlink_to(outside)
    commands = []
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew) if name == "brew" else None)
    monkeypatch.setattr(
        config.subprocess,
        "run",
        _homebrew_update_runner(
            commands, brew=brew, cellar=cellar, prefix=prefix, core=outside.resolve()
        ),
    )

    assert config._perform_homebrew_update("0.2.6") is False
    assert [str(brew), "upgrade", config.OPS_FORMULA] not in [
        command for command, _ in commands
    ]


def test_homebrew_update_blocks_formula_prefix_outside_homebrew_cellar(monkeypatch, tmp_path):
    brew, cellar, _, _ = _make_formula_layout(tmp_path)
    outside_prefix = tmp_path / "other-cellar" / "bluearch-aws-core" / "0.2.6"
    outside_core = outside_prefix / "bin" / "bluearch-aws-core"
    outside_core.parent.mkdir(parents=True)
    outside_core.write_text("#!/bin/sh\n", encoding="utf-8")
    outside_core.chmod(0o755)
    commands = []
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew) if name == "brew" else None)
    monkeypatch.setattr(
        config.subprocess,
        "run",
        _homebrew_update_runner(
            commands,
            brew=brew,
            cellar=cellar,
            prefix=outside_prefix.resolve(),
            core=outside_core.resolve(),
        ),
    )

    assert config._perform_homebrew_update("0.2.6") is False
    assert [str(brew), "upgrade", config.OPS_FORMULA] not in [
        command for command, _ in commands
    ]


@pytest.mark.parametrize(
    ("ops_prefix_output", "ops_prefix_returncode"),
    [
        ("relative/ops-prefix\n", 0),
        ("/first/ops-prefix\n/second/ops-prefix\n", 0),
        ("", 1),
    ],
)
def test_homebrew_update_fails_closed_for_malformed_or_failed_ops_prefix(
    monkeypatch,
    tmp_path,
    ops_prefix_output,
    ops_prefix_returncode,
):
    brew, cellar, prefix, core = _make_formula_layout(tmp_path)
    commands = []
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew))
    monkeypatch.setattr(
        config.subprocess,
        "run",
        _homebrew_update_runner(
            commands,
            brew=brew,
            cellar=cellar,
            prefix=prefix,
            core=core,
            ops_prefix_output=ops_prefix_output,
            ops_prefix_returncode=ops_prefix_returncode,
        ),
    )

    assert config._perform_homebrew_update("0.2.6") is False
    executed = [command for command, _ in commands]
    assert [str(brew), "upgrade", config.OPS_FORMULA] in executed
    assert [
        str(core),
        "start",
        "--daemon",
        "--web-apps",
        "bluearch-aws-ops",
    ] not in executed


def test_homebrew_update_rejects_ops_prefix_outside_exact_cellar(monkeypatch, tmp_path):
    brew, cellar, prefix, core = _make_formula_layout(tmp_path)
    outside_prefix = tmp_path / "other-cellar" / config.OPS_FORMULA_NAME / "0.13.9"
    outside_ops = outside_prefix / "bin" / config.PUBLIC_OPS_EXECUTABLE
    outside_ops.parent.mkdir(parents=True)
    outside_ops.write_text("#!/bin/sh\n", encoding="utf-8")
    outside_ops.chmod(0o755)
    commands = []
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew))
    monkeypatch.setattr(
        config.subprocess,
        "run",
        _homebrew_update_runner(
            commands,
            brew=brew,
            cellar=cellar,
            prefix=prefix,
            core=core,
            ops_prefix=outside_prefix.resolve(),
        ),
    )

    assert config._perform_homebrew_update("0.2.6") is False
    executed = [command for command, _ in commands]
    assert [str(brew), "upgrade", config.OPS_FORMULA] in executed
    assert [str(core), "start", "--daemon", "--web-apps", "bluearch-aws-ops"] not in executed


def test_homebrew_update_rejects_ops_prefix_for_wrong_formula(monkeypatch, tmp_path):
    brew, cellar, prefix, core = _make_formula_layout(tmp_path)
    wrong_prefix = cellar / "bluearch" / "0.13.9"
    wrong_ops = wrong_prefix / "bin" / config.PUBLIC_OPS_EXECUTABLE
    wrong_ops.parent.mkdir(parents=True)
    wrong_ops.write_text("#!/bin/sh\n", encoding="utf-8")
    wrong_ops.chmod(0o755)
    commands = []
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew))
    monkeypatch.setattr(
        config.subprocess,
        "run",
        _homebrew_update_runner(
            commands,
            brew=brew,
            cellar=cellar,
            prefix=prefix,
            core=core,
            ops_prefix=wrong_prefix.resolve(),
        ),
    )

    assert config._perform_homebrew_update("0.2.6") is False
    assert [
        str(core),
        "start",
        "--daemon",
        "--web-apps",
        "bluearch-aws-ops",
    ] not in [command for command, _ in commands]


def test_homebrew_update_rejects_ops_binary_that_escapes_formula_prefix(
    monkeypatch, tmp_path
):
    brew, cellar, prefix, core = _make_formula_layout(tmp_path)
    ops = cellar / config.OPS_FORMULA_NAME / "0.13.9" / "bin" / config.PUBLIC_OPS_EXECUTABLE
    outside = tmp_path / "outside" / config.PUBLIC_OPS_EXECUTABLE
    outside.parent.mkdir()
    outside.write_text("#!/bin/sh\n", encoding="utf-8")
    outside.chmod(0o755)
    ops.unlink()
    ops.symlink_to(outside)
    commands = []
    monkeypatch.setattr(config.shutil, "which", lambda name: str(brew))
    monkeypatch.setattr(
        config.subprocess,
        "run",
        _homebrew_update_runner(
            commands,
            brew=brew,
            cellar=cellar,
            prefix=prefix,
            core=core,
        ),
    )

    assert config._perform_homebrew_update("0.2.6") is False
    assert [
        str(core),
        "start",
        "--daemon",
        "--web-apps",
        "bluearch-aws-ops",
    ] not in [command for command, _ in commands]


def test_homebrew_detection_executes_resolved_exact_public_target(monkeypatch, tmp_path):
    resolved = tmp_path / "Cellar" / "bluearch-aws-ops" / "0.13.4" / "bin" / "bluearch-aws-ops"
    resolved.parent.mkdir(parents=True)
    resolved.write_text("#!/bin/sh\n", encoding="utf-8")
    resolved.chmod(0o755)
    public_link = tmp_path / "bin" / "bluearch-aws-ops"
    public_link.parent.mkdir()
    public_link.symlink_to(resolved)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="bluearch-aws-ops 0.13.4\n", stderr="")

    monkeypatch.setattr(config.subprocess, "run", run)

    installation = config.detect_homebrew_installation({"test": public_link})

    assert installation["installed"] is True
    assert installation["binary_path"] == str(public_link)
    assert installation["resolved_binary_path"] == str(resolved)
    assert installation["version"] == "bluearch-aws-ops 0.13.4"
    assert commands == [[str(resolved), "--version"]]


def test_homebrew_detection_rejects_public_link_to_legacy_target(monkeypatch, tmp_path):
    legacy = tmp_path / "Cellar" / "bluearch" / "0.13.3" / "bin" / "bluearch"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("#!/bin/sh\n", encoding="utf-8")
    legacy.chmod(0o755)
    public_link = tmp_path / "bin" / "bluearch-aws-ops"
    public_link.parent.mkdir()
    public_link.symlink_to(legacy)
    commands = []
    monkeypatch.setattr(
        config.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0),
    )

    assert config.detect_homebrew_installation({"test": public_link}) == {"installed": False}
    assert commands == []


def test_homebrew_detection_rejects_public_named_binary_from_legacy_formula(monkeypatch, tmp_path):
    renamed_legacy = tmp_path / "Cellar" / "bluearch" / "0.13.3" / "bin" / "bluearch-aws-ops"
    renamed_legacy.parent.mkdir(parents=True)
    renamed_legacy.write_text("#!/bin/sh\n", encoding="utf-8")
    renamed_legacy.chmod(0o755)
    public_link = tmp_path / "bin" / "bluearch-aws-ops"
    public_link.parent.mkdir()
    public_link.symlink_to(renamed_legacy)
    commands = []
    monkeypatch.setattr(
        config.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0),
    )

    assert config.detect_homebrew_installation({"test": public_link}) == {"installed": False}
    assert commands == []
