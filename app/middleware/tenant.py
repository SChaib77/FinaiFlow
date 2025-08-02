from fastapi import Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog
from typing import Optional

from app.core.database import get_db, TenantDB
from app.models.tenant import Tenant

logger = structlog.get_logger()


class TenantMiddleware:
    """Multi-tenant middleware for request routing"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)
            
            # Skip tenant resolution for health and system endpoints
            if request.url.path in ["/health", "/metrics", "/docs", "/redoc", "/openapi.json"]:
                await self.app(scope, receive, send)
                return
            
            # Determine tenant from request
            tenant_info = await self.resolve_tenant(request)
            
            if tenant_info:
                # Add tenant info to request state
                request.state.tenant_id = tenant_info.get("tenant_id")
                request.state.tenant = tenant_info.get("tenant")
                request.state.schema_name = tenant_info.get("schema_name")
        
        await self.app(scope, receive, send)
    
    async def resolve_tenant(self, request: Request) -> Optional[dict]:
        """Resolve tenant from request"""
        try:
            # Method 1: Subdomain-based tenant resolution
            host = request.headers.get("host", "")
            if "." in host:
                subdomain = host.split(".")[0]
                if subdomain and subdomain != "www":
                    tenant = await self.get_tenant_by_subdomain(subdomain)
                    if tenant:
                        return {
                            "tenant_id": str(tenant.id),
                            "tenant": tenant,
                            "schema_name": tenant.schema_name
                        }
            
            # Method 2: Header-based tenant resolution
            tenant_header = request.headers.get("X-Tenant-ID")
            if tenant_header:
                tenant = await self.get_tenant_by_id(tenant_header)
                if tenant:
                    return {
                        "tenant_id": str(tenant.id),
                        "tenant": tenant,
                        "schema_name": tenant.schema_name
                    }
            
            # Method 3: Path-based tenant resolution
            path_parts = request.url.path.strip("/").split("/")
            if len(path_parts) > 1 and path_parts[0] == "tenant":
                tenant_identifier = path_parts[1]
                tenant = await self.get_tenant_by_subdomain(tenant_identifier)
                if tenant:
                    return {
                        "tenant_id": str(tenant.id),
                        "tenant": tenant,
                        "schema_name": tenant.schema_name
                    }
            
            # Default tenant for development/testing
            if request.headers.get("host", "").startswith("localhost"):
                return {
                    "tenant_id": "default",
                    "tenant": None,
                    "schema_name": "public"
                }
            
            logger.warning("Could not resolve tenant", host=host, path=request.url.path)
            return None
            
        except Exception as e:
            logger.error("Tenant resolution failed", error=str(e))
            return None
    
    async def get_tenant_by_subdomain(self, subdomain: str) -> Optional[Tenant]:
        """Get tenant by subdomain"""
        try:
            # This would typically use dependency injection, but for middleware
            # we need to create our own session
            from app.core.database import async_session_maker
            
            async with async_session_maker() as session:
                result = await session.execute(
                    select(Tenant).where(
                        Tenant.subdomain == subdomain,
                        Tenant.is_active == True,
                        Tenant.is_suspended == False
                    )
                )
                return result.scalar_one_or_none()
                
        except Exception as e:
            logger.error("Failed to get tenant by subdomain", subdomain=subdomain, error=str(e))
            return None
    
    async def get_tenant_by_id(self, tenant_id: str) -> Optional[Tenant]:
        """Get tenant by ID"""
        try:
            from app.core.database import async_session_maker
            
            async with async_session_maker() as session:
                result = await session.execute(
                    select(Tenant).where(
                        Tenant.id == tenant_id,
                        Tenant.is_active == True,
                        Tenant.is_suspended == False
                    )
                )
                return result.scalar_one_or_none()
                
        except Exception as e:
            logger.error("Failed to get tenant by ID", tenant_id=tenant_id, error=str(e))
            return None


async def get_current_tenant(request: Request) -> Optional[Tenant]:
    """Get current tenant from request state"""
    return getattr(request.state, "tenant", None)


async def get_tenant_db(request: Request) -> TenantDB:
    """Get tenant-specific database connection"""
    tenant_id = getattr(request.state, "tenant_id", "default")
    return TenantDB(tenant_id)