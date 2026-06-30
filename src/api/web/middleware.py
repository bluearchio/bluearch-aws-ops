"""Exception handlers for AWS errors — maps boto3 exceptions to HTTP responses."""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

logger = logging.getLogger("bluearch.web")

# AWS error code -> HTTP status code
_ERROR_CODE_MAP = {
    "AccessDenied": 403,
    "AccessDeniedException": 403,
    "UnauthorizedAccess": 403,
    "ExpiredToken": 401,
    "ExpiredTokenException": 401,
    "InvalidClientTokenId": 401,
    "Throttling": 429,
    "ThrottlingException": 429,
    "RequestLimitExceeded": 429,
    "TooManyRequestsException": 429,
    "ResourceNotFoundException": 404,
    "ValidationException": 400,
}


async def handle_client_error(request: Request, exc: ClientError):
    code = exc.response.get("Error", {}).get("Code", "Unknown")
    message = exc.response.get("Error", {}).get("Message", str(exc))
    status = _ERROR_CODE_MAP.get(code, 502)
    logger.warning("AWS ClientError on %s %s: %s - %s", request.method, request.url.path, code, message)
    return JSONResponse(
        status_code=status,
        content={"detail": message, "code": code},
    )


async def handle_no_credentials(request: Request, exc: NoCredentialsError):
    logger.warning("No AWS credentials on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=401,
        content={"detail": "AWS credentials not configured", "code": "NoCredentials"},
    )


async def handle_botocore_error(request: Request, exc: BotoCoreError):
    logger.error("BotoCoreError on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=502,
        content={"detail": str(exc), "code": "AWSError"},
    )
