from fastapi import Request, HTTPException, status
import time
import structlog
from typing import Optional

from app.core.redis import cache
from app.core.config import settings

logger = structlog.get_logger()


class RateLimitMiddleware:
    """Rate limiting middleware"""
    
    def __init__(self, app):
        self.app = app
        self.enabled = settings.RATE_LIMIT_ENABLED
        self.requests_per_window = settings.RATE_LIMIT_REQUESTS
        self.window_seconds = settings.RATE_LIMIT_WINDOW
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.enabled:
            request = Request(scope, receive)
            
            # Skip rate limiting for health checks
            if request.url.path in ["/health", "/metrics"]:
                await self.app(scope, receive, send)
                return
            
            # Check rate limit
            if not await self.check_rate_limit(request):
                response = HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded. Please try again later."
                )
                
                # Send rate limit response
                await send({
                    'type': 'http.response.start',
                    'status': response.status_code,
                    'headers': [
                        [b'content-type', b'application/json'],
                        [b'x-ratelimit-limit', str(self.requests_per_window).encode()],
                        [b'x-ratelimit-window', str(self.window_seconds).encode()],
                    ]
                })
                await send({
                    'type': 'http.response.body',
                    'body': f'{{"detail": "{response.detail}"}}'.encode()
                })
                return
        
        await self.app(scope, receive, send)
    
    async def check_rate_limit(self, request: Request) -> bool:
        """Check if request is within rate limit"""
        try:
            # Get client identifier
            client_id = self.get_client_identifier(request)
            
            # Create rate limit key
            rate_key = f"rate_limit:{client_id}:{int(time.time() // self.window_seconds)}"
            
            # Get current count
            current_count = await cache.get(rate_key) or 0
            
            if current_count >= self.requests_per_window:
                logger.warning(
                    "Rate limit exceeded",
                    client_id=client_id,
                    current_count=current_count,
                    limit=self.requests_per_window
                )
                return False
            
            # Increment counter
            await cache.increment(rate_key)
            await cache.expire(rate_key, self.window_seconds)
            
            # Add rate limit headers to response (this is a simplified approach)
            request.state.rate_limit_remaining = self.requests_per_window - current_count - 1
            request.state.rate_limit_limit = self.requests_per_window
            
            return True
            
        except Exception as e:
            logger.error("Rate limit check failed", error=str(e))
            # Allow request on error to avoid blocking legitimate traffic
            return True
    
    def get_client_identifier(self, request: Request) -> str:
        """Get client identifier for rate limiting"""
        # Priority order: authenticated user > forwarded IP > client IP
        
        # Check if user is authenticated
        if hasattr(request.state, "current_user") and request.state.current_user:
            return f"user:{request.state.current_user.id}"
        
        # Check for forwarded IP (behind proxy/load balancer)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return f"ip:{forwarded_for.split(',')[0].strip()}"
        
        # Use client IP
        client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"


class EndpointRateLimiter:
    """Decorator for endpoint-specific rate limiting"""
    
    def __init__(self, requests: int, window: int):
        self.requests = requests
        self.window = window
    
    def __call__(self, func):
        async def wrapper(request: Request, *args, **kwargs):
            if not await self.check_endpoint_rate_limit(request):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded for this endpoint. Limit: {self.requests} per {self.window} seconds."
                )
            return await func(request, *args, **kwargs)
        
        return wrapper
    
    async def check_endpoint_rate_limit(self, request: Request) -> bool:
        """Check endpoint-specific rate limit"""
        try:
            # Get client identifier
            client_id = self.get_client_identifier(request)
            endpoint = request.url.path
            
            # Create endpoint-specific rate limit key
            rate_key = f"endpoint_rate:{client_id}:{endpoint}:{int(time.time() // self.window)}"
            
            # Get current count
            current_count = await cache.get(rate_key) or 0
            
            if current_count >= self.requests:
                logger.warning(
                    "Endpoint rate limit exceeded",
                    client_id=client_id,
                    endpoint=endpoint,
                    current_count=current_count,
                    limit=self.requests
                )
                return False
            
            # Increment counter
            await cache.increment(rate_key)
            await cache.expire(rate_key, self.window)
            
            return True
            
        except Exception as e:
            logger.error("Endpoint rate limit check failed", error=str(e))
            return True
    
    def get_client_identifier(self, request: Request) -> str:
        """Get client identifier"""
        if hasattr(request.state, "current_user") and request.state.current_user:
            return f"user:{request.state.current_user.id}"
        
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return f"ip:{forwarded_for.split(',')[0].strip()}"
        
        client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"


# Decorator instances for common use cases
login_rate_limit = EndpointRateLimiter(requests=5, window=300)  # 5 attempts per 5 minutes
api_rate_limit = EndpointRateLimiter(requests=1000, window=3600)  # 1000 requests per hour
auth_rate_limit = EndpointRateLimiter(requests=10, window=60)  # 10 requests per minute