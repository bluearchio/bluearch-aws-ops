"""Error handling decorators — composable stack for CLI commands.

Matches the tag-manager CLI pattern. Decorators are stacked:
    @handle_all_errors      <- catches everything
    def my_command():
        ...

Or composed individually:
    @require_aws_credentials
    @handle_aws_errors
    def my_command():
        ...
"""

import functools
import sys

import boto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    NoCredentialsError,
    PartialCredentialsError,
    ProfileNotFound,
)

from utils.display_utils import print_error, print_warning, print_info, console
from utils.logger_config import log


# ---------------------------------------------------------------------------
# Credential check
# ---------------------------------------------------------------------------

def require_aws_credentials(func):
    """Decorator: verify AWS credentials are available before running."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            sts = boto3.client("sts")
            sts.get_caller_identity()
        except NoCredentialsError:
            print_error("No AWS credentials found.")
            print_info("Configure credentials via:")
            console.print("  [cyan]export AWS_PROFILE=your-profile[/cyan]")
            console.print("  [cyan]aws sso login[/cyan]")
            _exit_safely()
            return
        except PartialCredentialsError:
            print_error("Incomplete AWS credentials. Check your configuration.")
            _exit_safely()
            return
        except ProfileNotFound as e:
            print_error(f"AWS profile not found: {e}")
            print_info("List available profiles: [cyan]aws configure list-profiles[/cyan]")
            _exit_safely()
            return
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("ExpiredToken", "ExpiredTokenException"):
                print_error("AWS credentials have expired.")
                print_info("Refresh with: [cyan]aws sso login[/cyan]")
                _exit_safely()
                return
            raise

        return func(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# AWS error handling
# ---------------------------------------------------------------------------

# Map AWS error codes to user-friendly messages
_AWS_ERROR_MESSAGES = {
    "AccessDenied": "Access denied. Check your IAM permissions.",
    "AccessDeniedException": "Access denied. Check your IAM permissions.",
    "UnauthorizedAccess": "Unauthorized. Check your IAM role/policy.",
    "ExpiredToken": "Session token expired. Run: aws sso login",
    "ExpiredTokenException": "Session token expired. Run: aws sso login",
    "Throttling": "API rate limit exceeded. Try again in a moment.",
    "ThrottlingException": "API rate limit exceeded. Try again in a moment.",
    "RequestLimitExceeded": "AWS request limit exceeded. Try again later.",
    "ServiceUnavailable": "AWS service temporarily unavailable. Try again.",
    "InternalError": "AWS internal error. Try again.",
}


def handle_aws_errors(func):
    """Decorator: catch and display AWS-specific errors gracefully."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            message = e.response.get("Error", {}).get("Message", str(e))

            friendly = _AWS_ERROR_MESSAGES.get(code)
            if friendly:
                print_error(friendly)
            else:
                print_error(f"AWS error ({code}): {message}")

            log.debug(f"ClientError: {code} - {message}")
            _exit_safely()
        except BotoCoreError as e:
            print_error(f"AWS SDK error: {e}")
            log.debug(f"BotoCoreError: {e}")
            _exit_safely()

    return wrapper


# ---------------------------------------------------------------------------
# Database error handling
# ---------------------------------------------------------------------------

def handle_database_errors(func):
    """Decorator: catch SQLAlchemy and SQLite errors."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_type = type(e).__name__
            # Check for SQLAlchemy/SQLite errors by name to avoid hard import
            if "OperationalError" in error_type or "SQLAlchemy" in error_type:
                print_error(f"Database error: {e}")
                print_info("Try: [cyan]bluearch setup database --force[/cyan]")
                log.debug(f"Database error: {e}")
                _exit_safely()
                return
            raise

    return wrapper


# ---------------------------------------------------------------------------
# Composed decorator
# ---------------------------------------------------------------------------

def handle_all_errors(func):
    """Composed decorator: credentials + AWS + database + generic errors.

    Usage:
        @handle_all_errors
        def my_command():
            ...
    """

    @functools.wraps(func)
    @require_aws_credentials
    @handle_aws_errors
    @handle_database_errors
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception as e:
            print_error(f"Unexpected error: {e}")
            log.debug(f"Unexpected error: {type(e).__name__}: {e}")
            _exit_safely()

    return wrapper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check_permission_error(e: ClientError) -> bool:
    """Check if a ClientError is a permission/access error."""
    code = e.response.get("Error", {}).get("Code", "")
    return code in (
        "AccessDenied",
        "AccessDeniedException",
        "UnauthorizedAccess",
        "AuthorizationError",
    )


def _exit_safely():
    """Exit without traceback. Handles both typer.Exit and sys.exit."""
    try:
        import typer
        raise typer.Exit(1)
    except ImportError:
        sys.exit(1)
