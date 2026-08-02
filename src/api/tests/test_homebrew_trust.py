from types import SimpleNamespace

from cli import config


def test_formula_trust_is_exact_and_formula_scoped(monkeypatch):
    commands = []
    monkeypatch.setattr(
        config.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0),
    )

    assert config._trust_homebrew_formula(config.CORE_FORMULA)
    assert config._trust_homebrew_formula(config.OPS_FORMULA)
    assert commands == [
        ["brew", "trust", "--formula", "bluearchio/tap/bluearch-aws-core"],
        ["brew", "trust", "--formula", "bluearchio/tap/bluearch-aws-ops"],
    ]


def test_active_homebrew_mutation_trusts_before_install(monkeypatch):
    commands = []
    monkeypatch.setattr(
        config.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0),
    )

    assert config._run_trusted_homebrew_formula("install", config.CORE_FORMULA)
    assert commands == [
        ["brew", "trust", "--formula", "bluearchio/tap/bluearch-aws-core"],
        ["brew", "install", "bluearchio/tap/bluearch-aws-core"],
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
