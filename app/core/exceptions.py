from typing import Optional, Dict, Any


class BaseAPIException(Exception):
    """Base exception for API errors"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(BaseAPIException):
    """Validation error exception"""
    pass


class AuthenticationError(BaseAPIException):
    """Authentication error exception"""
    pass


class AuthorizationError(BaseAPIException):
    """Authorization error exception"""
    pass


class NotFoundError(BaseAPIException):
    """Resource not found exception"""
    pass


class ConflictError(BaseAPIException):
    """Resource conflict exception"""
    pass


class RateLimitError(BaseAPIException):
    """Rate limit exceeded exception"""
    pass


class TenantError(BaseAPIException):
    """Tenant-related error exception"""
    pass


class ExternalServiceError(BaseAPIException):
    """External service error exception"""
    pass