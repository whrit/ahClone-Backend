"""
Test suite for custom exception handling.

Tests follow TDD approach - written before implementation.
Tests verify:
- Custom exception classes work correctly
- Exception handlers return proper HTTP status codes
- Error responses include request_id and timestamp
- Error messages are user-friendly (no stack traces)
- Exception handlers log errors properly
"""

import pytest
import uuid
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError as PydanticValidationError, field_validator
import logging

from app.core.exceptions import (
    SEOPlatformError,
    NotFoundError,
    AuthorizationError,
    ValidationError,
    RateLimitError,
    ExternalServiceError,
    QuotaExceededError,
    ErrorResponse,
)
from app.core.exception_handlers import register_exception_handlers


# Test fixtures
@pytest.fixture
def app():
    """Create a test FastAPI app with exception handlers registered."""
    app = FastAPI()
    register_exception_handlers(app)

    # Add test routes that raise various exceptions
    @app.get("/test/not-found/{resource_id}")
    async def test_not_found(resource_id: str):
        raise NotFoundError("Project", resource_id)

    @app.get("/test/unauthorized")
    async def test_unauthorized():
        raise AuthorizationError("delete this project")

    @app.get("/test/validation")
    async def test_validation():
        raise ValidationError("Invalid email format", field="email")

    @app.get("/test/rate-limit")
    async def test_rate_limit():
        raise RateLimitError(retry_after=120)

    @app.get("/test/external-service")
    async def test_external_service():
        raise ExternalServiceError("Google Search Console", "API quota exceeded")

    @app.get("/test/quota")
    async def test_quota():
        raise QuotaExceededError("API requests", 1000)

    @app.get("/test/generic-error")
    async def test_generic_error():
        raise SEOPlatformError("Something went wrong", code="INTERNAL_ERROR")

    # Pydantic validation test route
    class ItemModel(BaseModel):
        name: str
        price: float

        @field_validator('price')
        @classmethod
        def price_must_be_positive(cls, v):
            if v <= 0:
                raise ValueError('Price must be positive')
            return v

    @app.post("/test/pydantic-validation")
    async def test_pydantic_validation(item: ItemModel):
        return item

    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


# Test SEOPlatformError base exception
def test_seo_platform_error_basic():
    """Test SEOPlatformError base exception has correct attributes."""
    error = SEOPlatformError("Test error", code="TEST_CODE", details={"key": "value"})

    assert error.message == "Test error"
    assert error.code == "TEST_CODE"
    assert error.details == {"key": "value"}
    assert str(error) == "Test error"


def test_seo_platform_error_default_code():
    """Test SEOPlatformError uses default code when not provided."""
    error = SEOPlatformError("Test error")

    assert error.code == "INTERNAL_ERROR"
    assert error.details == {}


# Test NotFoundError returns 404
def test_not_found_error_returns_404(client):
    """Test NotFoundError returns HTTP 404 status code."""
    response = client.get("/test/not-found/123")

    assert response.status_code == 404
    data = response.json()

    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"
    assert "Project with id '123' not found" in data["error"]["message"]


def test_not_found_error_without_identifier():
    """Test NotFoundError message without identifier."""
    error = NotFoundError("User")

    assert error.message == "User not found"
    assert error.code == "NOT_FOUND"


def test_not_found_error_with_identifier():
    """Test NotFoundError message with identifier."""
    error = NotFoundError("Project", "abc-123")

    assert error.message == "Project with id 'abc-123' not found"
    assert error.code == "NOT_FOUND"


# Test AuthorizationError returns 403
def test_authorization_error_returns_403(client):
    """Test AuthorizationError returns HTTP 403 status code."""
    response = client.get("/test/unauthorized")

    assert response.status_code == 403
    data = response.json()

    assert "error" in data
    assert data["error"]["code"] == "UNAUTHORIZED"
    assert "not authorized to delete this project" in data["error"]["message"]


def test_authorization_error_default_message():
    """Test AuthorizationError default message."""
    error = AuthorizationError()

    assert error.message == "You are not authorized to access this resource"
    assert error.code == "UNAUTHORIZED"


def test_authorization_error_custom_action():
    """Test AuthorizationError custom action message."""
    error = AuthorizationError("modify this audit")

    assert error.message == "You are not authorized to modify this audit"
    assert error.code == "UNAUTHORIZED"


# Test ValidationError returns 422
def test_validation_error_returns_422(client):
    """Test ValidationError returns HTTP 422 status code."""
    response = client.get("/test/validation")

    assert response.status_code == 422
    data = response.json()

    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert "Invalid email format" in data["error"]["message"]
    assert data["error"]["details"]["field"] == "email"


def test_validation_error_with_field():
    """Test ValidationError includes field in details."""
    error = ValidationError("Invalid format", field="username")

    assert error.message == "Invalid format"
    assert error.code == "VALIDATION_ERROR"
    assert error.details == {"field": "username"}


def test_validation_error_without_field():
    """Test ValidationError without field."""
    error = ValidationError("Invalid input")

    assert error.message == "Invalid input"
    assert error.code == "VALIDATION_ERROR"
    assert error.details == {}


# Test RateLimitError returns 429
def test_rate_limit_error_returns_429(client):
    """Test RateLimitError returns HTTP 429 status code."""
    response = client.get("/test/rate-limit")

    assert response.status_code == 429
    data = response.json()

    assert "error" in data
    assert data["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Rate limit exceeded" in data["error"]["message"]
    assert data["error"]["details"]["retry_after"] == 120


def test_rate_limit_error_default_retry():
    """Test RateLimitError default retry_after value."""
    error = RateLimitError()

    assert "retry after 60 seconds" in error.message
    assert error.details["retry_after"] == 60


def test_rate_limit_error_custom_retry():
    """Test RateLimitError custom retry_after value."""
    error = RateLimitError(retry_after=300)

    assert "retry after 300 seconds" in error.message
    assert error.details["retry_after"] == 300


# Test ExternalServiceError returns 502
def test_external_service_error_returns_502(client):
    """Test ExternalServiceError returns HTTP 502 status code."""
    response = client.get("/test/external-service")

    assert response.status_code == 502
    data = response.json()

    assert "error" in data
    assert data["error"]["code"] == "EXTERNAL_SERVICE_ERROR"
    assert "Google Search Console" in data["error"]["message"]
    assert data["error"]["details"]["service"] == "Google Search Console"


def test_external_service_error_basic():
    """Test ExternalServiceError basic message."""
    error = ExternalServiceError("Google Ads")

    assert "Google Ads" in error.message
    assert "unavailable" in error.message
    assert error.code == "EXTERNAL_SERVICE_ERROR"
    assert error.details["service"] == "Google Ads"


def test_external_service_error_with_message():
    """Test ExternalServiceError with custom message."""
    error = ExternalServiceError("Google Analytics", "Rate limit exceeded")

    assert "Google Analytics" in error.message
    assert "Rate limit exceeded" in error.message
    assert error.details["service"] == "Google Analytics"


# Test QuotaExceededError
def test_quota_exceeded_error_returns_403(client):
    """Test QuotaExceededError returns HTTP 403 status code."""
    response = client.get("/test/quota")

    assert response.status_code == 403
    data = response.json()

    assert "error" in data
    assert data["error"]["code"] == "QUOTA_EXCEEDED"
    assert "API requests" in data["error"]["message"]
    assert data["error"]["details"]["resource"] == "API requests"
    assert data["error"]["details"]["limit"] == 1000


def test_quota_exceeded_error_attributes():
    """Test QuotaExceededError attributes."""
    error = QuotaExceededError("projects", 50)

    assert "projects" in error.message
    assert "50" in error.message
    assert error.code == "QUOTA_EXCEEDED"
    assert error.details["resource"] == "projects"
    assert error.details["limit"] == 50


# Test error response includes request_id
def test_error_response_includes_request_id(client):
    """Test error responses include a request_id for traceability."""
    response = client.get("/test/not-found/123")

    assert response.status_code == 404
    data = response.json()

    assert "error" in data
    assert "request_id" in data["error"]
    # Validate it's a valid UUID format
    try:
        uuid.UUID(data["error"]["request_id"])
        is_valid_uuid = True
    except ValueError:
        is_valid_uuid = False

    assert is_valid_uuid, "request_id should be a valid UUID"


# Test error response includes timestamp
def test_error_response_includes_timestamp(client):
    """Test error responses include an ISO timestamp."""
    response = client.get("/test/not-found/123")

    assert response.status_code == 404
    data = response.json()

    assert "error" in data
    assert "timestamp" in data["error"]

    # Validate it's a valid ISO timestamp
    try:
        datetime.fromisoformat(data["error"]["timestamp"])
        is_valid_timestamp = True
    except ValueError:
        is_valid_timestamp = False

    assert is_valid_timestamp, "timestamp should be a valid ISO format"


# Test error messages are user-friendly
def test_error_messages_are_user_friendly(client):
    """Test error messages don't expose internal details or stack traces."""
    response = client.get("/test/generic-error")

    assert response.status_code == 500
    data = response.json()

    # Should not contain stack trace keywords
    error_json_str = str(data)
    assert "Traceback" not in error_json_str
    assert "raise" not in error_json_str
    assert "File" not in error_json_str

    # Should have user-friendly structure
    assert "error" in data
    assert "message" in data["error"]
    assert "code" in data["error"]
    assert isinstance(data["error"]["message"], str)
    assert len(data["error"]["message"]) > 0


def test_pydantic_validation_error_user_friendly(client):
    """Test Pydantic validation errors are converted to user-friendly format."""
    response = client.post("/test/pydantic-validation", json={"name": "Test", "price": -10})

    assert response.status_code == 422
    data = response.json()

    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert data["error"]["message"] == "Validation failed"
    assert "errors" in data["error"]["details"]

    # Should have user-friendly error format
    errors = data["error"]["details"]["errors"]
    assert len(errors) > 0
    assert "field" in errors[0]
    assert "message" in errors[0]


# Test ErrorResponse class
def test_error_response_model_basic():
    """Test ErrorResponse model creates correct structure."""
    response = ErrorResponse(
        message="Test error",
        code="TEST_CODE",
        status_code=400,
        details={"key": "value"},
    )

    data = response.to_dict()

    assert "error" in data
    assert data["error"]["message"] == "Test error"
    assert data["error"]["code"] == "TEST_CODE"
    assert data["error"]["details"] == {"key": "value"}
    assert "request_id" in data["error"]
    assert "timestamp" in data["error"]


def test_error_response_model_auto_fields():
    """Test ErrorResponse auto-generates request_id and timestamp."""
    response = ErrorResponse(
        message="Test error",
        code="TEST_CODE",
        status_code=400,
    )

    data = response.to_dict()

    # Should have auto-generated fields
    assert "request_id" in data["error"]
    assert "timestamp" in data["error"]

    # Validate UUID
    try:
        uuid.UUID(data["error"]["request_id"])
        is_valid_uuid = True
    except ValueError:
        is_valid_uuid = False
    assert is_valid_uuid

    # Validate timestamp
    try:
        datetime.fromisoformat(data["error"]["timestamp"])
        is_valid_timestamp = True
    except ValueError:
        is_valid_timestamp = False
    assert is_valid_timestamp


def test_error_response_model_custom_request_id():
    """Test ErrorResponse accepts custom request_id."""
    custom_id = "custom-request-123"
    response = ErrorResponse(
        message="Test error",
        code="TEST_CODE",
        status_code=400,
        request_id=custom_id,
    )

    data = response.to_dict()
    assert data["error"]["request_id"] == custom_id


# Test exception handlers log errors properly
def test_exception_handler_logs_errors(client, caplog):
    """Test exception handlers log errors with appropriate context."""
    with caplog.at_level(logging.ERROR):
        response = client.get("/test/not-found/123")

        assert response.status_code == 404

        # Check that error was logged
        assert len(caplog.records) > 0

        # Find the relevant log record
        error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(error_logs) > 0

        # Verify log contains useful information
        log_record = error_logs[0]
        assert "SEOPlatformError" in log_record.message or "NOT_FOUND" in log_record.message


def test_validation_error_logging(client, caplog):
    """Test validation errors are logged."""
    with caplog.at_level(logging.ERROR):
        response = client.get("/test/validation")

        assert response.status_code == 422

        # Should have logged the error
        error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(error_logs) > 0


# Test different error scenarios
def test_multiple_errors_have_unique_request_ids(client):
    """Test each error response has a unique request_id."""
    response1 = client.get("/test/not-found/123")
    response2 = client.get("/test/not-found/456")

    data1 = response1.json()
    data2 = response2.json()

    request_id_1 = data1["error"]["request_id"]
    request_id_2 = data2["error"]["request_id"]

    assert request_id_1 != request_id_2


def test_error_response_structure_consistency(client):
    """Test all error responses have consistent structure."""
    test_endpoints = [
        "/test/not-found/123",
        "/test/unauthorized",
        "/test/validation",
        "/test/rate-limit",
        "/test/external-service",
        "/test/quota",
        "/test/generic-error",
    ]

    for endpoint in test_endpoints:
        response = client.get(endpoint)
        data = response.json()

        # All should have same structure
        assert "error" in data, f"Missing 'error' key in {endpoint}"
        assert "message" in data["error"], f"Missing 'message' in {endpoint}"
        assert "code" in data["error"], f"Missing 'code' in {endpoint}"
        assert "details" in data["error"], f"Missing 'details' in {endpoint}"
        assert "request_id" in data["error"], f"Missing 'request_id' in {endpoint}"
        assert "timestamp" in data["error"], f"Missing 'timestamp' in {endpoint}"
