from typer import Option

def alarm(config_targets: bool = Option(False, "--config-targets", "-c", help="Configure Slack and Email notification targets for alarms.")):
    """
    Manage CloudWatch Alarms and notification targets for recommendations.

    [yellow]Example:[/yellow]
    [green]bluearch alarm --config-targets[/green]
    """
    from utils.event_hooks import passthrough_decorator
    from aws.misc.error_handlings import error_handler
    from aws.misc.alarm_ui import configure_alarms, configure_targets
    from licensing.gate import requires_tier

    @passthrough_decorator
    @requires_tier("alarm:config")
    def execute_alarm():
        try:
            if config_targets:
                configure_targets()
            else:
                configure_alarms()
        except Exception as e:
            error_handler.handle_error(e)

    execute_alarm()
