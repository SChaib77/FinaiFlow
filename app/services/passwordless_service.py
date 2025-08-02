from typing import Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import secrets
import structlog

from app.core.security import security
from app.core.redis import cache
from app.core.exceptions import ValidationError, AuthenticationError
from app.models.user import User
from app.tasks.email import send_email

logger = structlog.get_logger()


class PasswordlessService:
    """Passwordless authentication service using magic links"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.token_expiry = 15  # minutes
        self.rate_limit_window = 60  # seconds
        self.max_requests_per_window = 3
    
    async def request_magic_link(self, email: str, ip_address: str) -> bool:
        """Request passwordless login magic link"""
        try:
            # Rate limiting
            rate_key = f"magic_link_rate:{ip_address}:{email}"
            current_requests = await cache.get(rate_key) or 0
            
            if current_requests >= self.max_requests_per_window:
                raise ValidationError("Too many requests. Please try again later.")
            
            # Increment rate limit counter
            await cache.set(rate_key, current_requests + 1, self.rate_limit_window)
            
            # Check if user exists
            result = await self.db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            
            if not user:
                # For security, don't reveal if user exists
                logger.warning("Magic link requested for non-existent user", email=email)
                return True  # Return True anyway to prevent user enumeration
            
            if not user.is_active:
                logger.warning("Magic link requested for inactive user", user_id=str(user.id))
                return True  # Return True anyway
            
            # Generate magic link token
            token = security.generate_secure_token(32)
            token_key = f"magic_link:{token}"
            
            # Store token in Redis with expiration
            token_data = {
                "user_id": str(user.id),
                "email": user.email,
                "ip_address": ip_address,
                "created_at": datetime.utcnow().isoformat()
            }
            
            await cache.set(token_key, token_data, self.token_expiry * 60)
            
            # Send magic link email
            magic_link = f"{settings.FRONTEND_URL}/auth/magic-link?token={token}"
            
            subject = "Your Magic Link to Sign In"
            body = f"""
            Hi {user.first_name},
            
            Click the link below to sign in to your account:
            
            {magic_link}
            
            This link will expire in {self.token_expiry} minutes.
            
            If you didn't request this, please ignore this email.
            """
            
            html_body = f"""
            <html>
                <body>
                    <h2>Sign In to Your Account</h2>
                    <p>Hi {user.first_name},</p>
                    <p>Click the button below to sign in to your account:</p>
                    <p>
                        <a href="{magic_link}" 
                           style="background-color: #007bff; color: white; padding: 10px 20px; 
                                  text-decoration: none; border-radius: 4px; display: inline-block;">
                            Sign In
                        </a>
                    </p>
                    <p>Or copy and paste this link into your browser:</p>
                    <p><a href="{magic_link}">{magic_link}</a></p>
                    <p>This link will expire in {self.token_expiry} minutes.</p>
                    <p>If you didn't request this, please ignore this email.</p>
                </body>
            </html>
            """
            
            # Send email asynchronously
            send_email.delay(user.email, subject, body, html_body)
            
            logger.info("Magic link sent", user_id=str(user.id), email=email)
            return True
            
        except Exception as e:
            logger.error("Magic link request failed", email=email, error=str(e))
            raise ValidationError("Failed to send magic link")
    
    async def verify_magic_link(self, token: str, ip_address: str) -> Optional[User]:
        """Verify magic link token and return user"""
        try:
            token_key = f"magic_link:{token}"
            token_data = await cache.get(token_key)
            
            if not token_data:
                raise AuthenticationError("Invalid or expired magic link")
            
            user_id = token_data.get("user_id")
            stored_ip = token_data.get("ip_address")
            
            # Optional: Enforce IP address validation
            # if stored_ip != ip_address:
            #     raise AuthenticationError("Magic link can only be used from the original IP address")
            
            # Get user
            user = await self.db.get(User, user_id)
            if not user or not user.is_active:
                raise AuthenticationError("User not found or inactive")
            
            # Delete token to prevent reuse
            await cache.delete(token_key)
            
            logger.info("Magic link verified", user_id=str(user.id))
            return user
            
        except Exception as e:
            logger.error("Magic link verification failed", token=token[:8] + "...", error=str(e))
            raise AuthenticationError("Invalid or expired magic link")
    
    async def send_email_verification(self, user_id: str) -> bool:
        """Send email verification link"""
        try:
            user = await self.db.get(User, user_id)
            if not user:
                return False
            
            if user.is_email_verified:
                return True
            
            # Generate verification token
            token = security.generate_secure_token(32)
            token_key = f"email_verify:{token}"
            
            # Store token in Redis (24 hour expiration)
            token_data = {
                "user_id": str(user.id),
                "email": user.email,
                "created_at": datetime.utcnow().isoformat()
            }
            
            await cache.set(token_key, token_data, 24 * 60 * 60)
            
            # Update user verification token
            user.email_verification_token = token
            await self.db.commit()
            
            # Send verification email
            verify_link = f"{settings.FRONTEND_URL}/auth/verify-email?token={token}"
            
            subject = "Verify Your Email Address"
            body = f"""
            Hi {user.first_name},
            
            Please verify your email address by clicking the link below:
            
            {verify_link}
            
            This link will expire in 24 hours.
            """
            
            html_body = f"""
            <html>
                <body>
                    <h2>Verify Your Email Address</h2>
                    <p>Hi {user.first_name},</p>
                    <p>Please verify your email address by clicking the button below:</p>
                    <p>
                        <a href="{verify_link}" 
                           style="background-color: #28a745; color: white; padding: 10px 20px; 
                                  text-decoration: none; border-radius: 4px; display: inline-block;">
                            Verify Email
                        </a>
                    </p>
                    <p>Or copy and paste this link into your browser:</p>
                    <p><a href="{verify_link}">{verify_link}</a></p>
                    <p>This link will expire in 24 hours.</p>
                </body>
            </html>
            """
            
            send_email.delay(user.email, subject, body, html_body)
            
            logger.info("Email verification sent", user_id=str(user.id))
            return True
            
        except Exception as e:
            logger.error("Email verification send failed", user_id=user_id, error=str(e))
            return False
    
    async def verify_email(self, token: str) -> bool:
        """Verify email address with token"""
        try:
            token_key = f"email_verify:{token}"
            token_data = await cache.get(token_key)
            
            if not token_data:
                raise ValidationError("Invalid or expired verification link")
            
            user_id = token_data.get("user_id")
            
            # Update user email verification status
            result = await self.db.execute(
                update(User)
                .where(User.id == user_id)
                .values(
                    is_email_verified=True,
                    email_verification_token=None
                )
            )
            
            if result.rowcount == 0:
                raise ValidationError("User not found")
            
            await self.db.commit()
            
            # Delete token
            await cache.delete(token_key)
            
            logger.info("Email verified", user_id=user_id)
            return True
            
        except Exception as e:
            logger.error("Email verification failed", token=token[:8] + "...", error=str(e))
            raise ValidationError("Email verification failed")
    
    async def send_password_reset(self, email: str) -> bool:
        """Send password reset link"""
        try:
            # Get user
            result = await self.db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            
            if not user:
                # For security, don't reveal if user exists
                return True
            
            # Generate reset token
            token = security.generate_secure_token(32)
            token_key = f"password_reset:{token}"
            
            # Store token in Redis (1 hour expiration)
            token_data = {
                "user_id": str(user.id),
                "email": user.email,
                "created_at": datetime.utcnow().isoformat()
            }
            
            await cache.set(token_key, token_data, 60 * 60)
            
            # Update user reset token
            user.password_reset_token = token
            user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
            await self.db.commit()
            
            # Send reset email
            reset_link = f"{settings.FRONTEND_URL}/auth/reset-password?token={token}"
            
            subject = "Reset Your Password"
            body = f"""
            Hi {user.first_name},
            
            You requested a password reset. Click the link below to reset your password:
            
            {reset_link}
            
            This link will expire in 1 hour.
            
            If you didn't request this, please ignore this email.
            """
            
            html_body = f"""
            <html>
                <body>
                    <h2>Reset Your Password</h2>
                    <p>Hi {user.first_name},</p>
                    <p>You requested a password reset. Click the button below to reset your password:</p>
                    <p>
                        <a href="{reset_link}" 
                           style="background-color: #dc3545; color: white; padding: 10px 20px; 
                                  text-decoration: none; border-radius: 4px; display: inline-block;">
                            Reset Password
                        </a>
                    </p>
                    <p>Or copy and paste this link into your browser:</p>
                    <p><a href="{reset_link}">{reset_link}</a></p>
                    <p>This link will expire in 1 hour.</p>
                    <p>If you didn't request this, please ignore this email.</p>
                </body>
            </html>
            """
            
            send_email.delay(user.email, subject, body, html_body)
            
            logger.info("Password reset sent", user_id=str(user.id))
            return True
            
        except Exception as e:
            logger.error("Password reset send failed", email=email, error=str(e))
            return False
    
    async def verify_password_reset(self, token: str, new_password: str) -> bool:
        """Verify password reset token and update password"""
        try:
            token_key = f"password_reset:{token}"
            token_data = await cache.get(token_key)
            
            if not token_data:
                raise ValidationError("Invalid or expired reset link")
            
            user_id = token_data.get("user_id")
            
            # Get user
            user = await self.db.get(User, user_id)
            if not user:
                raise ValidationError("User not found")
            
            # Update password
            user.set_password(new_password)
            user.password_reset_token = None
            user.password_reset_expires = None
            
            await self.db.commit()
            
            # Delete token
            await cache.delete(token_key)
            
            logger.info("Password reset completed", user_id=str(user.id))
            return True
            
        except Exception as e:
            logger.error("Password reset verification failed", error=str(e))
            raise ValidationError("Password reset failed")