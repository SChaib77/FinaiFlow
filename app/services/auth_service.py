from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import secrets
import structlog

from app.core.security import security, audit_logger
from app.core.redis import cache, RedisSession
from app.core.exceptions import AuthenticationError, ValidationError
from app.models.user import User
from app.models.auth import AuthToken, AuditLog
from app.schemas.auth import TokenResponse, LoginRequest

logger = structlog.get_logger()


class AuthService:
    """Authentication service with enterprise features"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def authenticate_user(self, email: str, password: str, ip_address: str, user_agent: str) -> User:
        """Authenticate user with security checks"""
        # Get user
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        
        if not user:
            audit_logger.log_auth_event(
                "login_failed", 
                ip_address=ip_address,
                user_agent=user_agent,
                success=False,
                details={"reason": "user_not_found", "email": email}
            )
            raise AuthenticationError("Invalid credentials")
        
        # Check if account is locked
        if user.locked_until and user.locked_until > datetime.utcnow():
            audit_logger.log_auth_event(
                "login_blocked",
                user_id=str(user.id),
                ip_address=ip_address,
                user_agent=user_agent,
                success=False,
                details={"reason": "account_locked"}
            )
            raise AuthenticationError("Account is temporarily locked")
        
        # Verify password
        if not user.verify_password(password):
            # Increment failed attempts
            user.failed_login_attempts += 1
            
            # Lock account after 5 failed attempts
            if user.failed_login_attempts >= 5:
                user.locked_until = datetime.utcnow() + timedelta(minutes=30)
                logger.warning("Account locked due to failed attempts", user_id=str(user.id))
            
            await self.db.commit()
            
            audit_logger.log_auth_event(
                "login_failed",
                user_id=str(user.id),
                ip_address=ip_address,
                user_agent=user_agent,
                success=False,
                details={"reason": "invalid_password", "failed_attempts": user.failed_login_attempts}
            )
            raise AuthenticationError("Invalid credentials")
        
        # Reset failed attempts on successful login
        user.failed_login_attempts = 0
        user.locked_until = None
        await self.db.commit()
        
        audit_logger.log_auth_event(
            "login_success",
            user_id=str(user.id),
            ip_address=ip_address,
            user_agent=user_agent,
            success=True
        )
        
        return user
    
    async def create_tokens(self, user: User, ip_address: str, user_agent: str) -> TokenResponse:
        """Create access and refresh tokens"""
        # Token payload
        token_data = {
            "sub": str(user.id),
            "email": user.email,
            "tenant_id": str(user.tenant_id),
            "is_superuser": user.is_superuser,
            "is_tenant_admin": user.is_tenant_admin
        }
        
        # Create tokens
        access_token = security.create_access_token(token_data)
        refresh_token = security.create_refresh_token({"sub": str(user.id)})
        
        # Store refresh token in database
        refresh_token_hash = security.hash_token(refresh_token)
        db_token = AuthToken(
            token_type="refresh",
            token_hash=refresh_token_hash,
            expires_at=datetime.utcnow() + timedelta(days=security.refresh_token_expire),
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        self.db.add(db_token)
        await self.db.commit()
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=security.access_token_expire * 60
        )
    
    async def refresh_access_token(self, refresh_token: str, ip_address: str) -> TokenResponse:
        """Refresh access token using refresh token"""
        try:
            # Verify refresh token
            payload = security.verify_token(refresh_token, "refresh")
            user_id = payload.get("sub")
            
            if not user_id:
                raise AuthenticationError("Invalid token payload")
            
            # Check if refresh token exists and is valid
            refresh_token_hash = security.hash_token(refresh_token)
            result = await self.db.execute(
                select(AuthToken).where(
                    AuthToken.token_hash == refresh_token_hash,
                    AuthToken.token_type == "refresh",
                    AuthToken.is_revoked == False
                )
            )
            db_token = result.scalar_one_or_none()
            
            if not db_token or db_token.is_expired:
                raise AuthenticationError("Invalid or expired refresh token")
            
            # Get user
            result = await self.db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            
            if not user or not user.is_active:
                raise AuthenticationError("User not found or inactive")
            
            # Update token last used
            db_token.last_used_at = datetime.utcnow()
            await self.db.commit()
            
            # Create new access token
            token_data = {
                "sub": str(user.id),
                "email": user.email,
                "tenant_id": str(user.tenant_id),
                "is_superuser": user.is_superuser,
                "is_tenant_admin": user.is_tenant_admin
            }
            
            access_token = security.create_access_token(token_data)
            
            audit_logger.log_auth_event(
                "token_refresh",
                user_id=str(user.id),
                ip_address=ip_address,
                success=True
            )
            
            return TokenResponse(
                access_token=access_token,
                refresh_token=refresh_token,  # Reuse existing refresh token
                token_type="bearer",
                expires_in=security.access_token_expire * 60
            )
            
        except Exception as e:
            audit_logger.log_auth_event(
                "token_refresh_failed",
                ip_address=ip_address,
                success=False,
                details={"error": str(e)}
            )
            raise AuthenticationError("Token refresh failed")
    
    async def revoke_token(self, refresh_token: str, user_id: str) -> bool:
        """Revoke refresh token"""
        try:
            refresh_token_hash = security.hash_token(refresh_token)
            result = await self.db.execute(
                select(AuthToken).where(
                    AuthToken.token_hash == refresh_token_hash,
                    AuthToken.user_id == user_id,
                    AuthToken.token_type == "refresh"
                )
            )
            db_token = result.scalar_one_or_none()
            
            if db_token:
                db_token.is_revoked = True
                await self.db.commit()
                
                audit_logger.log_auth_event(
                    "token_revoked",
                    user_id=user_id,
                    success=True
                )
                return True
            
            return False
            
        except Exception as e:
            logger.error("Token revocation failed", user_id=user_id, error=str(e))
            return False
    
    async def revoke_all_user_tokens(self, user_id: str) -> int:
        """Revoke all refresh tokens for a user"""
        try:
            result = await self.db.execute(
                select(AuthToken).where(
                    AuthToken.user_id == user_id,
                    AuthToken.token_type == "refresh",
                    AuthToken.is_revoked == False
                )
            )
            tokens = result.scalars().all()
            
            count = 0
            for token in tokens:
                token.is_revoked = True
                count += 1
            
            await self.db.commit()
            
            audit_logger.log_auth_event(
                "all_tokens_revoked",
                user_id=user_id,
                success=True,
                details={"revoked_count": count}
            )
            
            return count
            
        except Exception as e:
            logger.error("Bulk token revocation failed", user_id=user_id, error=str(e))
            return 0
    
    async def create_session(self, user_id: str, session_data: Dict[str, Any]) -> str:
        """Create user session in Redis"""
        session_id = security.generate_secure_token()
        session = RedisSession(session_id)
        
        await session.set_data({
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
            **session_data
        })
        
        return session_id
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get user session from Redis"""
        session = RedisSession(session_id)
        return await session.get_data()
    
    async def destroy_session(self, session_id: str) -> bool:
        """Destroy user session"""
        session = RedisSession(session_id)
        return await session.destroy()