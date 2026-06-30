def optin_hub():
    """
    Configure AWS Opt-In services settings.
    """
    from utils.event_hooks import passthrough_decorator
    from aws.misc.error_handlings import error_handler
    from licensing.gate import requires_tier
    from aws.wrappers.organizations import Organizations
    from rich.console import Console
    from aws.misc.optin_ui import OptInUI

    @passthrough_decorator
    @requires_tier("optin_hub")
    def show_optin_hub():
        try:
            console = Console()
            if not Organizations().is_account_delegated_admin_or_management():
                console.print("[yellow]You are currently not using a delegated admin or management account. To deploy the stack at the Organization level, please switch to one of those accounts. Alternatively, you can deploy the stack within a single account.[/yellow]")
                return
            else:
                ui = OptInUI()
                ui.run()
        except Exception as e:
            error_handler.handle_error(e)

    show_optin_hub()