from fastapi import Request, Response
import time
import uuid
import structlog
from typing import Callable

logger = structlog.get_logger()


class LoggingMiddleware:
    """Request/Response logging middleware"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)
            
            # Generate request ID
            request_id = str(uuid.uuid4())
            request.state.request_id = request_id
            
            # Start timer
            start_time = time.time()
            
            # Log request
            await self.log_request(request)
            
            # Process request and capture response
            response_info = {}
            
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    response_info["status_code"] = message["status"]
                    response_info["headers"] = dict(message.get("headers", []))
                elif message["type"] == "http.response.body":
                    response_info["body_size"] = len(message.get("body", b""))
                
                await send(message)
            
            try:
                await self.app(scope, receive, send_wrapper)
                
                # Log successful response
                duration = time.time() - start_time
                await self.log_response(request, response_info, duration, success=True)
                
            except Exception as e:
                # Log error response
                duration = time.time() - start_time
                await self.log_error(request, e, duration)
                raise
        else:
            await self.app(scope, receive, send)
    
    async def log_request(self, request: Request):
        """Log incoming request"""
        try:
            # Get client information
            client_ip = self.get_client_ip(request)
            user_agent = request.headers.get("user-agent", "")
            
            # Get user information if available
            user_id = None
            tenant_id = None
            if hasattr(request.state, "current_user") and request.state.current_user:
                user_id = str(request.state.current_user.id)
                tenant_id = str(request.state.current_user.tenant_id)
            elif hasattr(request.state, "tenant_id"):
                tenant_id = request.state.tenant_id
            
            # Log request
            logger.info(
                "HTTP Request",
                request_id=request.state.request_id,
                method=request.method,
                url=str(request.url),
                path=request.url.path,
                query_params=dict(request.query_params),
                headers=dict(request.headers),
                client_ip=client_ip,
                user_agent=user_agent,
                user_id=user_id,
                tenant_id=tenant_id,
                event_type="request"
            )
            
        except Exception as e:
            logger.error("Failed to log request", error=str(e))
    
    async def log_response(self, request: Request, response_info: dict, duration: float, success: bool = True):
        """Log response"""
        try:
            status_code = response_info.get("status_code", 0)
            body_size = response_info.get("body_size", 0)
            
            # Get user information
            user_id = None
            if hasattr(request.state, "current_user") and request.state.current_user:
                user_id = str(request.state.current_user.id)
            
            # Determine log level based on status code
            if status_code >= 500:
                log_level = "error"
            elif status_code >= 400:
                log_level = "warning"
            else:
                log_level = "info"
            
            # Log response
            logger.log(
                log_level.upper(),
                "HTTP Response",
                request_id=request.state.request_id,
                method=request.method,
                url=str(request.url),
                path=request.url.path,
                status_code=status_code,
                duration_ms=round(duration * 1000, 2),
                response_size_bytes=body_size,
                user_id=user_id,
                success=success,
                event_type="response"
            )
            
        except Exception as e:
            logger.error("Failed to log response", error=str(e))
    
    async def log_error(self, request: Request, error: Exception, duration: float):
        """Log error response"""
        try:
            user_id = None
            if hasattr(request.state, "current_user") and request.state.current_user:
                user_id = str(request.state.current_user.id)
            
            logger.error(
                "HTTP Error",
                request_id=request.state.request_id,
                method=request.method,
                url=str(request.url),
                path=request.url.path,
                duration_ms=round(duration * 1000, 2),
                error_type=type(error).__name__,
                error_message=str(error),
                user_id=user_id,
                success=False,
                event_type="error"
            )
            
        except Exception as e:
            logger.error("Failed to log error", error=str(e))
    
    def get_client_ip(self, request: Request) -> str:
        """Get client IP address considering proxies"""
        # Check X-Forwarded-For header (proxy/load balancer)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        # Check X-Real-IP header (Nginx proxy)
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        
        # Fall back to client host
        return request.client.host if request.client else "unknown"


class StructuredLogger:
    """Structured logging setup"""
    
    @staticmethod
    def configure_logging():
        """Configure structured logging"""
        import logging
        from app.core.config import settings
        
        # Configure structlog
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="ISO"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer()
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
        
        # Configure standard library logging
        logging.basicConfig(
            level=getattr(logging, settings.LOG_LEVEL.upper()),
            format="%(message)s"
        )


# Initialize structured logging
StructuredLogger.configure_logging()