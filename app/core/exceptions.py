"""
Custom exception classes for the SEO Platform.

This module provides a hierarchy of custom exceptions with user-friendly
error messages and structured error responses. All exceptions inherit from
SEOPlatformError base class.

Exception Hierarchy:
- SEOPlatformError (base)
  - NotFoundError (404)
  - AuthorizationError (403)
  - ValidationError (422)
  - RateLimitError (429)
  - ExternalServiceError (502)
  - QuotaExceededError (403)
"""

from typing import Any
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
import uuid
from datetime import datetime, timezone


class SEOPlatformError(Exception):
    """Base exception for all platform errors.

    All custom exceptions should inherit from this class.
    Provides consistent error structure with code, message, and details.

    Attributes:
        message: Human-readable error message
        code: Machine-readable error code (e.g., "NOT_FOUND", "VALIDATION_ERROR")
        details: Additional context about the error
    """

    def __init__(self, message: str, code: str = "INTERNAL_ERROR", details: dict = None):
        """Initialize SEOPlatformError.

        Args:
            message: Human-readable error message
            code: Machine-readable error code (default: "INTERNAL_ERROR")
            details: Additional error context (default: {})
        """
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)


class NotFoundError(SEOPlatformError):
    """Resource not found (HTTP 404).

    Use when a requested resource doesn't exist in the database.

    Example:
        raise NotFoundError("Project", "abc-123")
        # -> "Project with id 'abc-123' not found"
    """

    def __init__(self, resource: str, identifier: str = None):
        """Initialize NotFoundError.

        Args:
            resource: Type of resource (e.g., "Project", "User", "Audit")
            identifier: Resource identifier (optional)
        """
        message = f"{resource} not found"
        if identifier:
            message = f"{resource} with id '{identifier}' not found"
        super().__init__(message, code="NOT_FOUND")


class AuthorizationError(SEOPlatformError):
    """User not authorized for action (HTTP 403).

    Use when a user lacks permission to perform an action.

    Example:
        raise AuthorizationError("delete this project")
        # -> "You are not authorized to delete this project"
    """

    def __init__(self, action: str = "access this resource"):
        """Initialize AuthorizationError.

        Args:
            action: Action the user is not authorized to perform
                   (default: "access this resource")
        """
        super().__init__(f"You are not authorized to {action}", code="UNAUTHORIZED")


class ValidationError(SEOPlatformError):
    """Input validation failed (HTTP 422).

    Use when user input fails validation rules.

    Example:
        raise ValidationError("Invalid email format", field="email")
    """

    def __init__(self, message: str, field: str = None):
        """Initialize ValidationError.

        Args:
            message: Validation error message
            field: Field name that failed validation (optional)
        """
        details = {"field": field} if field else {}
        super().__init__(message, code="VALIDATION_ERROR", details=details)


class RateLimitError(SEOPlatformError):
    """Rate limit exceeded (HTTP 429).

    Use when a user exceeds rate limits.

    Example:
        raise RateLimitError(retry_after=120)
        # -> "Rate limit exceeded. Please retry after 120 seconds"
    """

    def __init__(self, retry_after: int = 60):
        """Initialize RateLimitError.

        Args:
            retry_after: Seconds to wait before retrying (default: 60)
        """
        super().__init__(
            f"Rate limit exceeded. Please retry after {retry_after} seconds",
            code="RATE_LIMIT_EXCEEDED",
            details={"retry_after": retry_after},
        )


class ExternalServiceError(SEOPlatformError):
    """External service (Google, etc.) failed (HTTP 502).

    Use when an external API or service is unavailable or returns an error.

    Example:
        raise ExternalServiceError("Google Search Console", "API quota exceeded")
        # -> "External service 'Google Search Console' is unavailable: API quota exceeded"
    """

    def __init__(self, service: str, message: str = None):
        """Initialize ExternalServiceError.

        Args:
            service: Name of the external service (e.g., "Google Ads")
            message: Additional error message (optional)
        """
        msg = f"External service '{service}' is unavailable"
        if message:
            msg = f"{msg}: {message}"
        super().__init__(msg, code="EXTERNAL_SERVICE_ERROR", details={"service": service})


class QuotaExceededError(SEOPlatformError):
    """Usage quota exceeded (HTTP 403).

    Use when a user exceeds their usage quota for a resource.

    Example:
        raise QuotaExceededError("projects", 50)
        # -> "Quota exceeded for projects. Limit is 50"
    """

    def __init__(self, resource: str, limit: int):
        """Initialize QuotaExceededError.

        Args:
            resource: Type of resource (e.g., "projects", "API requests")
            limit: The quota limit that was exceeded
        """
        super().__init__(
            f"Quota exceeded for {resource}. Limit is {limit}",
            code="QUOTA_EXCEEDED",
            details={"resource": resource, "limit": limit},
        )


class ErrorResponse:
    """Standardized error response format.

    Provides consistent error response structure across all API endpoints.
    Automatically generates request_id and timestamp for traceability.

    Example response:
        {
            "error": {
                "message": "Project not found",
                "code": "NOT_FOUND",
                "details": {},
                "request_id": "550e8400-e29b-41d4-a716-446655440000",
                "timestamp": "2025-12-24T10:30:00.123456"
            }
        }
    """

    def __init__(
        self,
        message: str,
        code: str,
        status_code: int,
        details: dict = None,
        request_id: str = None,
    ):
        """Initialize ErrorResponse.

        Args:
            message: Human-readable error message
            code: Machine-readable error code
            status_code: HTTP status code (not included in response, used for FastAPI)
            details: Additional error context (default: {})
            request_id: Unique request identifier (auto-generated if not provided)
        """
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        self.request_id = request_id or str(uuid.uuid4())
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """Convert error response to dictionary format.

        Returns:
            Dictionary with standardized error structure
        """
        return {
            "error": {
                "message": self.message,
                "code": self.code,
                "details": self.details,
                "request_id": self.request_id,
                "timestamp": self.timestamp,
            }
        }
