from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timedelta

from .base import BaseModel


class AuthToken(BaseModel):
    __tablename__ = "auth_tokens"
    
    token_type = Column(String(20), nullable=False)  # access, refresh
    token_hash = Column(String(255), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)
    
    # Metadata
    user_agent = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    
    # Relationships
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="auth_tokens")
    
    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at
    
    @property
    def is_valid(self) -> bool:
        return not (self.is_revoked or self.is_expired)


class OAuth2Account(BaseModel):
    __tablename__ = "oauth2_accounts"
    
    provider = Column(String(50), nullable=False)  # google, github, microsoft
    provider_user_id = Column(String(100), nullable=False)
    provider_username = Column(String(100), nullable=True)
    provider_email = Column(String(100), nullable=True)
    
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    
    # Additional provider data
    provider_data = Column(Text, nullable=True)  # JSON string
    
    # Relationships
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="oauth2_accounts")
    
    def __repr__(self):
        return f"<OAuth2Account(provider='{self.provider}', user_id='{self.user_id}')>"


class TwoFactorAuth(BaseModel):
    __tablename__ = "two_factor_auth"
    
    secret_key = Column(String(32), nullable=False)
    backup_codes = Column(Text, nullable=True)  # JSON array of backup codes
    is_enabled = Column(Boolean, default=False)
    last_used_at = Column(DateTime, nullable=True)
    
    # Relationships
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    user = relationship("User", back_populates="two_factor_auth")


class AuditLog(BaseModel):
    __tablename__ = "audit_logs"
    
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(UUID(as_uuid=True), nullable=True)
    
    # Request details
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    
    # Additional context
    details = Column(Text, nullable=True)  # JSON string
    status = Column(String(20), default="success")  # success, failure, warning
    
    # Relationships
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    user = relationship("User", back_populates="audit_logs")
    
    def __repr__(self):
        return f"<AuditLog(action='{self.action}', user_id='{self.user_id}')>"