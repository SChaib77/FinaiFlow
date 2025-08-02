from sqlalchemy import Column, String, Text, Integer, JSON, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID

from .base import BaseModel


class Tenant(BaseModel):
    __tablename__ = "tenants"
    
    name = Column(String(100), nullable=False)
    subdomain = Column(String(50), unique=True, nullable=False, index=True)
    domain = Column(String(100), nullable=True)
    
    # Configuration
    settings = Column(JSON, default=dict)
    max_users = Column(Integer, default=10)
    max_storage_mb = Column(Integer, default=1000)
    
    # Status
    is_suspended = Column(Boolean, default=False)
    suspension_reason = Column(Text, nullable=True)
    
    # Billing
    plan = Column(String(50), default="basic")
    billing_email = Column(String(100), nullable=True)
    
    # Contact
    contact_name = Column(String(100), nullable=False)
    contact_email = Column(String(100), nullable=False)
    contact_phone = Column(String(20), nullable=True)
    
    # Database schema name for multi-tenancy
    schema_name = Column(String(50), nullable=False)
    
    def __repr__(self):
        return f"<Tenant(name='{self.name}', subdomain='{self.subdomain}')>"