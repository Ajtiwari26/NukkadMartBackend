"""
Redis Connection Utility (Upstash REST API)
Manages Redis connections for caching, session state, and real-time data
Uses Upstash serverless Redis with REST API
"""
import httpx
from typing import Optional, Any, List
import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Upstash Redis REST API client"""

    _http_client: Optional[httpx.AsyncClient] = None
    client = None  # For backward compatibility

    @classmethod
    async def connect(cls) -> None:
        """Initialize HTTP client for Upstash Redis"""
        try:
            cls._http_client = httpx.AsyncClient(
                base_url=settings.UPSTASH_REDIS_REST_URL,
                headers={
                    "Authorization": f"Bearer {settings.UPSTASH_REDIS_REST_TOKEN}"
                },
                timeout=30.0
            )
            # Verify connection with PING
            response = await cls._execute("PING")
            if response == "PONG":
                logger.info("Connected to Upstash Redis")
                cls.client = cls  # For backward compatibility
            else:
                raise Exception(f"Unexpected PING response: {response}")
        except Exception as e:
            logger.error(f"Failed to connect to Upstash Redis: {e}")
            # Create a mock client for development if Redis is unavailable
            cls.client = cls
            logger.warning("Running with Redis in mock mode")

    @classmethod
    async def disconnect(cls) -> None:
        """Close HTTP client"""
        if cls._http_client:
            await cls._http_client.aclose()
            cls._http_client = None
            logger.info("Disconnected from Upstash Redis")

    @classmethod
    async def _execute(cls, *args) -> Any:
        """Execute a Redis command via REST API"""
        if not cls._http_client:
            logger.warning("Redis not connected, returning None")
            return None

        try:
            # Use POST with JSON body for all commands to avoid URL length limits
            # Upstash REST API accepts: POST / with body ["COMMAND", "arg1", "arg2", ...]
            command_list = [str(arg) for arg in args]
            response = await cls._http_client.post(
                "/",
                json=command_list
            )
            response.raise_for_status()
            data = response.json()
            return data.get("result")
        except Exception as e:
            logger.error(f"Redis command failed: {args[0]} - {e}")
            return None

    @classmethod
    async def _execute_post(cls, commands: List[List[str]]) -> List[Any]:
        """Execute multiple Redis commands via pipeline"""
        if not cls._http_client:
            return [None] * len(commands)

        try:
            response = await cls._http_client.post(
                "/pipeline",
                json=commands
            )
            response.raise_for_status()
            results = response.json()
            return [r.get("result") for r in results]
        except Exception as e:
            logger.error(f"Redis pipeline failed: {e}")
            return [None] * len(commands)

    # ==================== Basic Operations ====================

    @classmethod
    async def get(cls, key: str) -> Optional[str]:
        """Get a value by key"""
        return await cls._execute("GET", key)

    @classmethod
    async def set(cls, key: str, value: str) -> bool:
        """Set a value"""
        result = await cls._execute("SET", key, value)
        return result == "OK"

    @classmethod
    async def setex(cls, key: str, seconds: int, value: str) -> bool:
        """Set a value with expiration"""
        result = await cls._execute("SETEX", key, str(seconds), value)
        return result == "OK"

    @classmethod
    async def delete(cls, key: str) -> int:
        """Delete a key"""
        result = await cls._execute("DEL", key)
        return result or 0

    @classmethod
    async def expire(cls, key: str, seconds: int) -> bool:
        """Set key expiration"""
        result = await cls._execute("EXPIRE", key, str(seconds))
        return result == 1

    @classmethod
    async def hset(cls, key: str, mapping: dict = None, **kwargs) -> int:
        """Set hash fields"""
        data = mapping or kwargs
        if not data:
            return 0

        # Build command: HSET key field1 value1 field2 value2 ...
        args = ["HSET", key]
        for field, value in data.items():
            args.extend([field, str(value)])

        result = await cls._execute(*args)
        return result or 0

    @classmethod
    async def hget(cls, key: str, field: str) -> Optional[str]:
        """Get a hash field"""
        return await cls._execute("HGET", key, field)

    @classmethod
    async def hgetall(cls, key: str) -> dict:
        """Get all hash fields"""
        result = await cls._execute("HGETALL", key)
        if not result:
            return {}

        # Convert list [field1, value1, field2, value2] to dict
        if isinstance(result, list):
            return dict(zip(result[::2], result[1::2]))
        return result if isinstance(result, dict) else {}

    @classmethod
    async def publish(cls, channel: str, message: str) -> int:
        """Publish a message to a channel"""
        if isinstance(message, dict):
            message = json.dumps(message)
        result = await cls._execute("PUBLISH", channel, message)
        return result or 0

    # ==================== Cart Operations ====================

    @classmethod
    async def set_cart(cls, session_id: str, cart_data: dict) -> None:
        """Store cart state in Redis with TTL"""
        key = f"cart:{session_id}"
        await cls.setex(key, settings.REDIS_CART_TTL, json.dumps(cart_data))

    @classmethod
    async def get_cart(cls, session_id: str) -> Optional[dict]:
        """Retrieve cart state from Redis"""
        key = f"cart:{session_id}"
        data = await cls.get(key)
        return json.loads(data) if data else None

    @classmethod
    async def delete_cart(cls, session_id: str) -> None:
        """Delete cart from Redis"""
        key = f"cart:{session_id}"
        await cls.delete(key)

    @classmethod
    async def update_cart_ttl(cls, session_id: str) -> None:
        """Refresh cart TTL on activity"""
        key = f"cart:{session_id}"
        await cls.expire(key, settings.REDIS_CART_TTL)

    # ==================== Session Tracking ====================

    @classmethod
    async def set_session(cls, session_id: str, session_data: dict) -> None:
        """Store user session for nudge engine tracking"""
        key = f"session:{session_id}"
        # Store as JSON string for simplicity with REST API
        await cls.setex(key, settings.REDIS_SESSION_TTL, json.dumps(session_data))

    @classmethod
    async def get_session(cls, session_id: str) -> Optional[dict]:
        """Retrieve session data"""
        key = f"session:{session_id}"
        data = await cls.get(key)
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return None
        return None

    @classmethod
    async def update_abandonment_score(cls, session_id: str, score: float) -> None:
        """Update the abandonment probability score"""
        session = await cls.get_session(session_id)
        if session:
            session["abandonment_score"] = score
            await cls.set_session(session_id, session)

    # ==================== Order State ====================

    @classmethod
    async def set_order_state(cls, order_id: str, order_data: dict) -> None:
        """Store active order state"""
        key = f"order:{order_id}"
        await cls.setex(key, settings.REDIS_ORDER_TTL, json.dumps(order_data))

    @classmethod
    async def get_order_state(cls, order_id: str) -> Optional[dict]:
        """Retrieve active order state"""
        key = f"order:{order_id}"
        data = await cls.get(key)
        return json.loads(data) if data else None

    @classmethod
    async def update_order_status(cls, order_id: str, status: str) -> None:
        """Update order status"""
        order = await cls.get_order_state(order_id)
        if order:
            order["status"] = status
            await cls.set_order_state(order_id, order)

    # ==================== Inventory Cache ====================

    @classmethod
    async def cache_inventory(cls, store_id: str, product_id: str, quantity: int) -> None:
        """Cache inventory level with 5 minute TTL"""
        key = f"inventory:{store_id}:{product_id}"
        await cls.setex(key, 300, str(quantity))

    @classmethod
    async def get_cached_inventory(cls, store_id: str, product_id: str) -> Optional[int]:
        """Get cached inventory level"""
        key = f"inventory:{store_id}:{product_id}"
        data = await cls.get(key)
        return int(data) if data else None

    @classmethod
    async def invalidate_inventory(cls, store_id: str, product_id: str) -> None:
        """Invalidate inventory cache on update"""
        key = f"inventory:{store_id}:{product_id}"
        await cls.delete(key)

    # ==================== Pub/Sub (Limited with REST) ====================

    @classmethod
    def subscribe(cls, *channels: str):
        """Subscribe to Redis channels - Note: Limited support with REST API"""
        logger.warning("Pub/Sub subscribe not fully supported with Upstash REST API")
        return None


async def get_redis() -> RedisClient:
    """Dependency to get Redis client"""
    if RedisClient._http_client is None:
        await RedisClient.connect()
    return RedisClient
