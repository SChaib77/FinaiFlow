from datetime import datetime, timedelta
from sqlalchemy import delete
import structlog

from app.core.celery_app import celery_app
from app.core.database import async_session_maker
from app.models.auth import AuthToken, AuditLog

logger = structlog.get_logger()


@celery_app.task(name="app.tasks.cleanup.cleanup_expired_tokens")
async def cleanup_expired_tokens():
    """Remove expired authentication tokens"""
    try:
        async with async_session_maker() as session:
            # Delete expired tokens
            result = await session.execute(
                delete(AuthToken).where(
                    AuthToken.expires_at < datetime.utcnow()
                )
            )
            await session.commit()
            
            deleted_count = result.rowcount
            logger.info("Cleaned up expired tokens", count=deleted_count)
            return {"deleted_tokens": deleted_count}
            
    except Exception as e:
        logger.error("Token cleanup failed", error=str(e))
        raise


@celery_app.task(name="app.tasks.cleanup.cleanup_old_audit_logs")
async def cleanup_old_audit_logs(days_to_keep: int = 90):
    """Remove old audit logs"""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
        
        async with async_session_maker() as session:
            # Delete old audit logs
            result = await session.execute(
                delete(AuditLog).where(
                    AuditLog.created_at < cutoff_date
                )
            )
            await session.commit()
            
            deleted_count = result.rowcount
            logger.info("Cleaned up old audit logs", count=deleted_count, days=days_to_keep)
            return {"deleted_logs": deleted_count, "cutoff_date": cutoff_date.isoformat()}
            
    except Exception as e:
        logger.error("Audit log cleanup failed", error=str(e))
        raise


@celery_app.task(name="app.tasks.cleanup.cleanup_revoked_tokens")
async def cleanup_revoked_tokens(days_to_keep: int = 7):
    """Remove old revoked tokens"""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
        
        async with async_session_maker() as session:
            # Delete old revoked tokens
            result = await session.execute(
                delete(AuthToken).where(
                    AuthToken.is_revoked == True,
                    AuthToken.updated_at < cutoff_date
                )
            )
            await session.commit()
            
            deleted_count = result.rowcount
            logger.info("Cleaned up revoked tokens", count=deleted_count, days=days_to_keep)
            return {"deleted_tokens": deleted_count, "cutoff_date": cutoff_date.isoformat()}
            
    except Exception as e:
        logger.error("Revoked token cleanup failed", error=str(e))
        raise