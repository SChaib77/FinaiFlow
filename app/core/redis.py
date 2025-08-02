import redis.asyncio as redis
from redis.asyncio import Redis
from typing import Optional, Any
import json
import structlog
from contextlib import asynccontextmanager

from app.core.config import settings

logger = structlog.get_logger()

# Redis connection pool
redis_pool: Optional[Redis] = None


async def init_redis():
    """Initialize Redis connection"""
    global redis_pool
    try:
        redis_pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            password=settings.REDIS_PASSWORD,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20
        )
        # Create Redis client
        client = Redis(connection_pool=redis_pool)
        # Test connection
        await client.ping()
        logger.info("Redis connection established")
    except Exception as e:
        logger.error("Redis connection failed", error=str(e))
        raise


async def get_redis() -> Redis:
    """Get Redis client"""
    if redis_pool is None:
        await init_redis()
    return Redis(connection_pool=redis_pool)


class RedisCache:
    """Redis cache manager"""
    
    def __init__(self):
        self.redis = None
    
    async def _get_client(self) -> Redis:
        if self.redis is None:
            self.redis = await get_redis()
        return self.redis
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        try:
            client = await self._get_client()
            value = await client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error("Redis get failed", key=key, error=str(e))
            return None
    
    async def set(self, key: str, value: Any, expire: int = 3600) -> bool:
        """Set value in cache with expiration"""
        try:
            client = await self._get_client()
            await client.setex(key, expire, json.dumps(value, default=str))
            return True
        except Exception as e:
            logger.error("Redis set failed", key=key, error=str(e))
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        try:
            client = await self._get_client()
            await client.delete(key)
            return True
        except Exception as e:
            logger.error("Redis delete failed", key=key, error=str(e))
            return False
    
    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        try:
            client = await self._get_client()
            return await client.exists(key) > 0
        except Exception as e:
            logger.error("Redis exists failed", key=key, error=str(e))
            return False
    
    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment counter"""
        try:
            client = await self._get_client()
            return await client.incrby(key, amount)
        except Exception as e:
            logger.error("Redis increment failed", key=key, error=str(e))
            return 0
    
    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration for key"""
        try:
            client = await self._get_client()
            return await client.expire(key, seconds)
        except Exception as e:
            logger.error("Redis expire failed", key=key, error=str(e))
            return False


class RedisSession:
    """Redis session manager"""
    
    def __init__(self, session_id: str, prefix: str = "session"):
        self.session_id = session_id
        self.key = f"{prefix}:{session_id}"
        self.cache = RedisCache()
    
    async def get_data(self) -> dict:
        """Get all session data"""
        data = await self.cache.get(self.key)
        return data or {}
    
    async def set_data(self, data: dict, expire: int = 86400) -> bool:
        """Set session data with expiration (default 24 hours)"""
        return await self.cache.set(self.key, data, expire)
    
    async def get(self, key: str, default: Any = None) -> Any:
        """Get specific session value"""
        data = await self.get_data()
        return data.get(key, default)
    
    async def set(self, key: str, value: Any) -> bool:
        """Set specific session value"""
        data = await self.get_data()
        data[key] = value
        return await self.set_data(data)
    
    async def delete(self, key: str) -> bool:
        """Delete specific session key"""
        data = await self.get_data()
        if key in data:
            del data[key]
            return await self.set_data(data)
        return True
    
    async def destroy(self) -> bool:
        """Destroy entire session"""
        return await self.cache.delete(self.key)
    
    async def regenerate(self, new_session_id: str) -> bool:
        """Regenerate session ID"""
        data = await self.get_data()
        await self.destroy()
        self.session_id = new_session_id
        self.key = f"session:{new_session_id}"
        return await self.set_data(data)


# Global cache instance
cache = RedisCache()