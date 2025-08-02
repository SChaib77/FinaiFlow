from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy import MetaData, text
from typing import AsyncGenerator
import structlog

from app.core.config import settings

logger = structlog.get_logger()

# Multi-tenant database setup
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,
    echo=settings.ENVIRONMENT == "development"
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()


async def init_db():
    """Initialize database and create schemas"""
    try:
        async with engine.begin() as conn:
            # Create public schema tables
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Database initialized successfully")
    except Exception as e:
        logger.error("Database initialization failed", error=str(e))
        raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Database dependency"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


class TenantDB:
    """Multi-tenant database manager with schema isolation"""
    
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.schema_name = f"tenant_{tenant_id}"
    
    async def create_tenant_schema(self):
        """Create tenant-specific schema"""
        async with engine.begin() as conn:
            await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self.schema_name}"))
            # Set search path for tenant
            await conn.execute(text(f"SET search_path TO {self.schema_name}, public"))
            # Create tenant-specific tables
            await conn.run_sync(Base.metadata.create_all)
            logger.info(f"Created schema for tenant: {self.tenant_id}")
    
    async def drop_tenant_schema(self):
        """Drop tenant schema and all data"""
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {self.schema_name} CASCADE"))
            logger.info(f"Dropped schema for tenant: {self.tenant_id}")
    
    async def get_tenant_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get database session with tenant schema context"""
        async with async_session_maker() as session:
            try:
                # Set schema search path for this session
                await session.execute(text(f"SET search_path TO {self.schema_name}, public"))
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()


async def get_tenant_db(tenant_id: str) -> AsyncGenerator[AsyncSession, None]:
    """Get tenant-specific database session"""
    tenant_db = TenantDB(tenant_id)
    async for session in tenant_db.get_tenant_session():
        yield session