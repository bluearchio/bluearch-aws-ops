from cli import interactive


def test_interactive_dashboard_action_only_prints_core_managed_start(monkeypatch):
    """The interactive menu must never call the hidden product web starter."""
    output = []
    monkeypatch.setattr(interactive.console, "print", lambda message="": output.append(str(message)))

    interactive._dispatch("web-help")

    rendered = "\n".join(output)
    assert "bluearch-aws-core start --daemon" in rendered
    assert "bluearch-aws-ops web start" not in rendered
    assert "Start the web dashboard" not in interactive.MENU_ITEMS["6"][1]
