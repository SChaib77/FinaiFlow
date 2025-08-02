from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.core.security import security, audit_logger
from app.core.exceptions import AuthenticationError, ValidationError
from app.services.auth_service import AuthService
from app.services.oauth_service import OAuth2Service
from app.services.totp_service import TOTPService
from app.services.passwordless_service import PasswordlessService
from app.schemas.auth import (
    LoginRequest, TokenResponse, RefreshTokenRequest,
    PasswordResetRequest, PasswordResetConfirm, ChangePasswordRequest,
    TwoFactorSetupResponse, TwoFactorVerifyRequest, TwoFactorLoginRequest,
    OAuth2AuthRequest, UserProfile
)
from app.middleware.auth import get_current_user
from app.models.user import User

router = APIRouter()
bearer_scheme = HTTPBearer()


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """Authenticate user and return tokens"""
    try:
        auth_service = AuthService(db)
        totp_service = TOTPService(db)
        
        ip_address = request.client.host
        user_agent = request.headers.get("user-agent", "")
        
        # Authenticate user
        user = await auth_service.authenticate_user(
            login_data.email,
            login_data.password,
            ip_address,
            user_agent
        )
        
        # Check if 2FA is enabled
        if await totp_service.is_2fa_enabled(str(user.id)):
            # Return special response indicating 2FA required
            return JSONResponse(
                status_code=200,
                content={
                    "requires_2fa": True,
                    "user_id": str(user.id),
                    "message": "Two-factor authentication required"
                }
            )
        
        # Create tokens
        tokens = await auth_service.create_tokens(user, ip_address, user_agent)
        
        # Create session if remember_me is enabled
        if login_data.remember_me:
            await auth_service.create_session(str(user.id), {
                "ip_address": ip_address,
                "user_agent": user_agent
            })
        
        return tokens
        
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed"
        )


@router.post("/login/2fa", response_model=TokenResponse)
async def login_with_2fa(
    request: Request,
    login_data: TwoFactorLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """Authenticate user with 2FA"""
    try:
        auth_service = AuthService(db)
        totp_service = TOTPService(db)
        
        ip_address = request.client.host
        user_agent = request.headers.get("user-agent", "")
        
        # Authenticate user
        user = await auth_service.authenticate_user(
            login_data.email,
            login_data.password,
            ip_address,
            user_agent
        )
        
        # Verify 2FA code
        if not await totp_service.verify_2fa_login(str(user.id), login_data.totp_code):
            raise AuthenticationError("Invalid 2FA code")
        
        # Create tokens
        tokens = await auth_service.create_tokens(user, ip_address, user_agent)
        return tokens
        
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: Request,
    refresh_data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """Refresh access token"""
    try:
        auth_service = AuthService(db)
        ip_address = request.client.host
        
        tokens = await auth_service.refresh_access_token(
            refresh_data.refresh_token,
            ip_address
        )
        return tokens
        
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )


@router.post("/logout")
async def logout(
    refresh_data: RefreshTokenRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Logout user and revoke refresh token"""
    try:
        auth_service = AuthService(db)
        
        await auth_service.revoke_token(
            refresh_data.refresh_token,
            str(current_user.id)
        )
        
        audit_logger.log_auth_event(
            "logout",
            user_id=str(current_user.id),
            success=True
        )
        
        return {"message": "Logged out successfully"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Logout failed"
        )


@router.post("/logout-all")
async def logout_all_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Logout from all sessions"""
    try:
        auth_service = AuthService(db)
        
        revoked_count = await auth_service.revoke_all_user_tokens(str(current_user.id))
        
        return {"message": f"Logged out from {revoked_count} sessions"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Logout failed"
        )


@router.post("/password-reset")
async def request_password_reset(
    reset_data: PasswordResetRequest,
    db: AsyncSession = Depends(get_db)
):
    """Request password reset"""
    try:
        passwordless_service = PasswordlessService(db)
        await passwordless_service.send_password_reset(reset_data.email)
        
        return {"message": "Password reset link sent to email"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send password reset email"
        )


@router.post("/password-reset/confirm")
async def confirm_password_reset(
    reset_data: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db)
):
    """Confirm password reset"""
    try:
        passwordless_service = PasswordlessService(db)
        success = await passwordless_service.verify_password_reset(
            reset_data.token,
            reset_data.new_password
        )
        
        if success:
            return {"message": "Password reset successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token"
            )
            
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/change-password")
async def change_password(
    password_data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Change user password"""
    try:
        # Verify current password
        if not current_user.verify_password(password_data.current_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect"
            )
        
        # Update password
        current_user.set_password(password_data.new_password)
        await db.commit()
        
        # Revoke all existing tokens for security
        auth_service = AuthService(db)
        await auth_service.revoke_all_user_tokens(str(current_user.id))
        
        audit_logger.log_auth_event(
            "password_changed",
            user_id=str(current_user.id),
            success=True
        )
        
        return {"message": "Password changed successfully"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password"
        )


@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Setup 2FA for user"""
    try:
        totp_service = TOTPService(db)
        setup_data = await totp_service.setup_2fa(str(current_user.id))
        
        return TwoFactorSetupResponse(
            secret_key=setup_data["secret_key"],
            qr_code_url=f"data:image/png;base64,{setup_data['qr_code_data']}",
            backup_codes=setup_data["backup_codes"]
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to setup 2FA"
        )


@router.post("/2fa/verify")
async def verify_2fa_setup(
    verify_data: TwoFactorVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Verify 2FA setup"""
    try:
        totp_service = TOTPService(db)
        success = await totp_service.verify_2fa_setup(str(current_user.id), verify_data.code)
        
        if success:
            audit_logger.log_auth_event(
                "2fa_enabled",
                user_id=str(current_user.id),
                success=True
            )
            return {"message": "2FA enabled successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid 2FA code"
            )
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify 2FA"
        )


@router.post("/2fa/disable")
async def disable_2fa(
    verify_data: TwoFactorVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Disable 2FA"""
    try:
        totp_service = TOTPService(db)
        success = await totp_service.disable_2fa(str(current_user.id), verify_data.code)
        
        if success:
            audit_logger.log_auth_event(
                "2fa_disabled",
                user_id=str(current_user.id),
                success=True
            )
            return {"message": "2FA disabled successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid 2FA code"
            )
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disable 2FA"
        )


@router.post("/magic-link")
async def request_magic_link(
    request: Request,
    email_data: PasswordResetRequest,
    db: AsyncSession = Depends(get_db)
):
    """Request passwordless magic link"""
    try:
        passwordless_service = PasswordlessService(db)
        ip_address = request.client.host
        
        await passwordless_service.request_magic_link(email_data.email, ip_address)
        
        return {"message": "Magic link sent to email"}
        
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send magic link"
        )


@router.get("/magic-link/verify")
async def verify_magic_link(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """Verify magic link and login"""
    try:
        passwordless_service = PasswordlessService(db)
        auth_service = AuthService(db)
        
        ip_address = request.client.host
        user_agent = request.headers.get("user-agent", "")
        
        # Verify magic link
        user = await passwordless_service.verify_magic_link(token, ip_address)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired magic link"
            )
        
        # Create tokens
        tokens = await auth_service.create_tokens(user, ip_address, user_agent)
        
        audit_logger.log_auth_event(
            "magic_link_login",
            user_id=str(user.id),
            ip_address=ip_address,
            success=True
        )
        
        return tokens
        
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )


@router.get("/oauth/{provider}")
async def oauth_authorize(provider: str, redirect_uri: str, state: str):
    """Get OAuth2 authorization URL"""
    try:
        oauth_service = OAuth2Service(None)  # No DB needed for URL generation
        auth_url = await oauth_service.get_authorization_url(provider, redirect_uri, state)
        
        return {"authorization_url": auth_url}
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/oauth/{provider}/callback")
async def oauth_callback(
    request: Request,
    provider: str,
    callback_data: OAuth2AuthRequest,
    db: AsyncSession = Depends(get_db)
):
    """Handle OAuth2 callback"""
    try:
        oauth_service = OAuth2Service(db)
        auth_service = AuthService(db)
        
        ip_address = request.client.host
        user_agent = request.headers.get("user-agent", "")
        
        # Get tenant from request (implement tenant detection logic)
        tenant_id = "default-tenant-id"  # This should be determined from request
        
        # Authenticate with OAuth2
        user = await oauth_service.authenticate_with_code(
            provider,
            callback_data.code,
            "redirect_uri",  # Should match the one used in authorization
            tenant_id
        )
        
        # Create tokens
        tokens = await auth_service.create_tokens(user, ip_address, user_agent)
        
        audit_logger.log_auth_event(
            f"oauth_login_{provider}",
            user_id=str(user.id),
            ip_address=ip_address,
            success=True
        )
        
        return tokens
        
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )


@router.get("/profile", response_model=UserProfile)
async def get_profile(current_user: User = Depends(get_current_user)):
    """Get current user profile"""
    return UserProfile.from_orm(current_user)