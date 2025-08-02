import pyotp
import qrcode
from io import BytesIO
import base64
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import secrets
import json
import structlog

from app.core.security import security, encryption
from app.core.exceptions import ValidationError, NotFoundError
from app.models.user import User
from app.models.auth import TwoFactorAuth

logger = structlog.get_logger()


class TOTPService:
    """Two-Factor Authentication service using TOTP"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    def generate_secret_key(self) -> str:
        """Generate a new TOTP secret key"""
        return pyotp.random_base32()
    
    def generate_backup_codes(self, count: int = 10) -> List[str]:
        """Generate backup codes for 2FA recovery"""
        return [secrets.token_hex(4).upper() for _ in range(count)]
    
    def generate_qr_code(self, secret_key: str, user_email: str, issuer_name: str = "FinaiFlow") -> str:
        """Generate QR code for TOTP setup"""
        totp_uri = pyotp.totp.TOTP(secret_key).provisioning_uri(
            name=user_email,
            issuer_name=issuer_name
        )
        
        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(totp_uri)
        qr.make(fit=True)
        
        # Convert to base64 image
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        return base64.b64encode(buffer.getvalue()).decode()
    
    def verify_totp_code(self, secret_key: str, code: str, window: int = 1) -> bool:
        """Verify TOTP code with time window tolerance"""
        try:
            totp = pyotp.TOTP(secret_key)
            return totp.verify(code, valid_window=window)
        except Exception as e:
            logger.error("TOTP verification failed", error=str(e))
            return False
    
    def verify_backup_code(self, backup_codes: List[str], code: str) -> Tuple[bool, List[str]]:
        """Verify backup code and return updated backup codes list"""
        code_upper = code.upper().strip()
        
        if code_upper in backup_codes:
            # Remove used backup code
            updated_codes = [c for c in backup_codes if c != code_upper]
            return True, updated_codes
        
        return False, backup_codes
    
    async def setup_2fa(self, user_id: str) -> dict:
        """Setup 2FA for user"""
        # Get user
        user = await self.db.get(User, user_id)
        if not user:
            raise NotFoundError("User not found")
        
        # Check if 2FA already exists
        result = await self.db.execute(
            select(TwoFactorAuth).where(TwoFactorAuth.user_id == user_id)
        )
        existing_2fa = result.scalar_one_or_none()
        
        # Generate new secret and backup codes
        secret_key = self.generate_secret_key()
        backup_codes = self.generate_backup_codes()
        
        # Encrypt sensitive data
        encrypted_secret = encryption.encrypt(secret_key)
        encrypted_backup_codes = encryption.encrypt(json.dumps(backup_codes))
        
        if existing_2fa:
            # Update existing 2FA setup
            existing_2fa.secret_key = encrypted_secret
            existing_2fa.backup_codes = encrypted_backup_codes
            existing_2fa.is_enabled = False  # User needs to verify setup
        else:
            # Create new 2FA setup
            two_factor_auth = TwoFactorAuth(
                user_id=user_id,
                secret_key=encrypted_secret,
                backup_codes=encrypted_backup_codes,
                is_enabled=False
            )
            self.db.add(two_factor_auth)
        
        await self.db.commit()
        
        # Generate QR code
        qr_code_data = self.generate_qr_code(secret_key, user.email)
        
        logger.info("2FA setup initiated", user_id=user_id)
        
        return {
            "secret_key": secret_key,
            "qr_code_data": qr_code_data,
            "backup_codes": backup_codes
        }
    
    async def verify_2fa_setup(self, user_id: str, code: str) -> bool:
        """Verify 2FA setup with TOTP code"""
        # Get 2FA record
        result = await self.db.execute(
            select(TwoFactorAuth).where(TwoFactorAuth.user_id == user_id)
        )
        two_factor_auth = result.scalar_one_or_none()
        
        if not two_factor_auth:
            raise NotFoundError("2FA setup not found")
        
        # Decrypt secret key
        secret_key = encryption.decrypt(two_factor_auth.secret_key)
        
        # Verify TOTP code
        if self.verify_totp_code(secret_key, code):
            # Enable 2FA
            two_factor_auth.is_enabled = True
            await self.db.commit()
            
            logger.info("2FA enabled", user_id=user_id)
            return True
        
        return False
    
    async def disable_2fa(self, user_id: str, code: str) -> bool:
        """Disable 2FA with verification"""
        # Get 2FA record
        result = await self.db.execute(
            select(TwoFactorAuth).where(TwoFactorAuth.user_id == user_id)
        )
        two_factor_auth = result.scalar_one_or_none()
        
        if not two_factor_auth or not two_factor_auth.is_enabled:
            return False
        
        # Decrypt secret and backup codes
        secret_key = encryption.decrypt(two_factor_auth.secret_key)
        backup_codes = json.loads(encryption.decrypt(two_factor_auth.backup_codes))
        
        # Verify code (TOTP or backup code)
        is_valid_totp = self.verify_totp_code(secret_key, code)
        is_valid_backup, _ = self.verify_backup_code(backup_codes, code)
        
        if is_valid_totp or is_valid_backup:
            # Disable 2FA
            two_factor_auth.is_enabled = False
            await self.db.commit()
            
            logger.info("2FA disabled", user_id=user_id)
            return True
        
        return False
    
    async def verify_2fa_login(self, user_id: str, code: str) -> bool:
        """Verify 2FA code during login"""
        # Get 2FA record
        result = await self.db.execute(
            select(TwoFactorAuth).where(
                TwoFactorAuth.user_id == user_id,
                TwoFactorAuth.is_enabled == True
            )
        )
        two_factor_auth = result.scalar_one_or_none()
        
        if not two_factor_auth:
            return False
        
        # Decrypt secret and backup codes
        secret_key = encryption.decrypt(two_factor_auth.secret_key)
        backup_codes = json.loads(encryption.decrypt(two_factor_auth.backup_codes))
        
        # Verify TOTP code first
        if self.verify_totp_code(secret_key, code):
            # Update last used time
            from datetime import datetime
            two_factor_auth.last_used_at = datetime.utcnow()
            await self.db.commit()
            return True
        
        # Try backup code
        is_valid_backup, updated_codes = self.verify_backup_code(backup_codes, code)
        if is_valid_backup:
            # Update backup codes and last used time
            two_factor_auth.backup_codes = encryption.encrypt(json.dumps(updated_codes))
            two_factor_auth.last_used_at = datetime.utcnow()
            await self.db.commit()
            
            logger.info("Backup code used for 2FA", user_id=user_id, 
                       remaining_codes=len(updated_codes))
            return True
        
        return False
    
    async def regenerate_backup_codes(self, user_id: str, code: str) -> Optional[List[str]]:
        """Regenerate backup codes after verification"""
        # Get 2FA record
        result = await self.db.execute(
            select(TwoFactorAuth).where(
                TwoFactorAuth.user_id == user_id,
                TwoFactorAuth.is_enabled == True
            )
        )
        two_factor_auth = result.scalar_one_or_none()
        
        if not two_factor_auth:
            return None
        
        # Verify current code
        secret_key = encryption.decrypt(two_factor_auth.secret_key)
        if not self.verify_totp_code(secret_key, code):
            return None
        
        # Generate new backup codes
        new_backup_codes = self.generate_backup_codes()
        two_factor_auth.backup_codes = encryption.encrypt(json.dumps(new_backup_codes))
        await self.db.commit()
        
        logger.info("Backup codes regenerated", user_id=user_id)
        return new_backup_codes
    
    async def is_2fa_enabled(self, user_id: str) -> bool:
        """Check if 2FA is enabled for user"""
        result = await self.db.execute(
            select(TwoFactorAuth).where(
                TwoFactorAuth.user_id == user_id,
                TwoFactorAuth.is_enabled == True
            )
        )
        return result.scalar_one_or_none() is not None