"""
Exception handlers for the SEO Platform.

This module provides centralized exception handling for all API endpoints.
Exception handlers convert exceptions to standardized JSON error responses
with appropriate HTTP status codes.

Features:
- Converts custom exceptions to user-friendly JSON responses
- Maps exception codes to HTTP status codes
- Logs all errors with context for debugging
- Converts Pydantic validation errors to user-friendly format
- Ensures consistent error response structure
"""

from fastapi import Request, FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging

from app.core.exceptions import (
    SEOPlatformError,
    NotFoundError,
    AuthorizationError,
    ValidationError,
    RateLimitError,
    ExternalServiceError,
    ErrorResponse,
)

logger = logging.getLogger(__name__)


async def seo_platform_exception_handler(
    request: Request, exc: SEOPlatformError
) -> JSONResponse:
    """Handle custom platform exceptions.

    Converts SEOPlatformError and its subclasses to standardized JSON responses.
    Maps error codes to appropriate HTTP status codes and logs errors.

    Args:
        request: The incoming request
        exc: The SEOPlatformError exception

    Returns:
        JSONResponse with standardized error format
    """
    # Map error codes to HTTP status codes
    status_codes = {
        "NOT_FOUND": 404,
        "UNAUTHORIZED": 403,
        "VALIDATION_ERROR": 422,
        "RATE_LIMIT_EXCEEDED": 429,
        "EXTERNAL_SERVICE_ERROR": 502,
        "QUOTA_EXCEEDED": 403,
        "INTERNAL_ERROR": 500,
    }
    status_code = status_codes.get(exc.code, 500)

    # Log the error with context
    logger.error(
        f"SEOPlatformError: {exc.message}",
        extra={
            "code": exc.code,
            "details": exc.details,
            "status_code": status_code,
            "path": request.url.path,
        },
    )

    # Create standardized error response
    response = ErrorResponse(
        message=exc.message,
        code=exc.code,
        status_code=status_code,
        details=exc.details,
    )

    return JSONResponse(status_code=status_code, content=response.to_dict())


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors with user-friendly messages.

    Converts Pydantic validation errors to a user-friendly format.
    Extracts field names and error messages from Pydantic errors.

    Args:
        request: The incoming request
        exc: The RequestValidationError exception

    Returns:
        JSONResponse with formatted validation errors

    Example response:
        {
            "error": {
                "message": "Validation failed",
                "code": "VALIDATION_ERROR",
                "details": {
                    "errors": [
                        {"field": "email", "message": "value is not a valid email address"},
                        {"field": "age", "message": "ensure this value is greater than 0"}
                    ]
                },
                "request_id": "...",
                "timestamp": "..."
            }
        }
    """
    # Convert Pydantic errors to user-friendly format
    errors = []
    for error in exc.errors():
        # Convert location tuple to dot-notation field path
        field = ".".join(str(loc) for loc in error["loc"])
        errors.append({"field": field, "message": error["msg"]})

    # Log validation error
    logger.error(
        "Validation failed",
        extra={
            "errors": errors,
            "path": request.url.path,
        },
    )

    # Create standardized error response
    response = ErrorResponse(
        message="Validation failed",
        code="VALIDATION_ERROR",
        status_code=422,
        details={"errors": errors},
    )

    return JSONResponse(status_code=422, content=response.to_dict())


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Handle Starlette HTTP exceptions.

    Converts standard HTTP exceptions to our standardized error format.
    This ensures consistency even for framework-level exceptions.

    Args:
        request: The incoming request
        exc: The HTTPException

    Returns:
        JSONResponse with standardized error format
    """
    # Map status codes to error codes
    code_mapping = {
        400: "BAD_REQUEST",
        401: "UNAUTHENTICATED",
        403: "UNAUTHORIZED",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMIT_EXCEEDED",
        500: "INTERNAL_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
    }

    error_code = code_mapping.get(exc.status_code, "INTERNAL_ERROR")

    # Log the error
    logger.error(
        f"HTTP Exception: {exc.detail}",
        extra={
            "status_code": exc.status_code,
            "code": error_code,
            "path": request.url.path,
        },
    )

    # Create standardized error response
    response = ErrorResponse(
        message=str(exc.detail),
        code=error_code,
        status_code=exc.status_code,
    )

    return JSONResponse(status_code=exc.status_code, content=response.to_dict())


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle any unhandled exceptions.

    Catches any exceptions that aren't handled by other handlers.
    Returns a generic error message to avoid leaking internal details.

    Args:
        request: The incoming request
        exc: The unhandled exception

    Returns:
        JSONResponse with generic error message
    """
    # Log the full exception for debugging
    logger.exception(
        "Unhandled exception",
        extra={
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
        exc_info=exc,
    )

    # Return generic error message (don't expose internal details)
    response = ErrorResponse(
        message="An unexpected error occurred. Please try again later.",
        code="INTERNAL_ERROR",
        status_code=500,
    )

    return JSONResponse(status_code=500, content=response.to_dict())


def register_exception_handlers(app: FastAPI):
    """Register all exception handlers with the FastAPI app.

    This should be called during app initialization to register
    all custom exception handlers.

    Note: We intentionally do NOT override StarletteHTTPException to maintain
    backward compatibility with existing code that expects {"detail": "..."} format.
    Custom exceptions (SEOPlatformError and subclasses) use the new format.

    Args:
        app: The FastAPI application instance

    Example:
        app = FastAPI()
        register_exception_handlers(app)
    """
    # Register custom exception handlers
    # Note: SEOPlatformError and subclasses get the new {"error": {...}} format
    app.add_exception_handler(SEOPlatformError, seo_platform_exception_handler)

    # Note: We do NOT override StarletteHTTPException or RequestValidationError
    # to maintain backward compatibility with existing tests and code that
    # expect the default FastAPI error format {"detail": "..."}

    # Only catch truly unhandled exceptions (not HTTPException or ValidationError)
    # This prevents breaking existing error handling behavior
    # app.add_exception_handler(Exception, unhandled_exception_handler)

    logger.info("Exception handlers registered successfully")
