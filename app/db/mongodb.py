"""
MongoDB Connection Utility
Manages MongoDB connections using Motor (async driver)
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Optional
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class MongoDB:
    """MongoDB connection manager"""

    client: Optional[AsyncIOMotorClient] = None
    database: Optional[AsyncIOMotorDatabase] = None

    @classmethod
    async def connect(cls) -> None:
        """Establish connection to MongoDB"""
        try:
            cls.client = AsyncIOMotorClient(
                settings.MONGODB_URL,
                maxPoolSize=100,
                minPoolSize=10,
                serverSelectionTimeoutMS=5000
            )
            cls.database = cls.client[settings.MONGODB_DATABASE]

            # Verify connection
            await cls.client.admin.command('ping')
            logger.info(f"Connected to MongoDB: {settings.MONGODB_DATABASE}")

            # Create indexes
            await cls._create_indexes()

        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    @classmethod
    async def disconnect(cls) -> None:
        """Close MongoDB connection"""
        if cls.client:
            cls.client.close()
            logger.info("Disconnected from MongoDB")

    @classmethod
    async def _create_indexes(cls) -> None:
        """Create necessary indexes for collections"""
        if cls.database is None:
            return

        # Products collection indexes
        products = cls.database.products
        await products.create_index([("store_id", 1), ("category", 1)])
        await products.create_index([("store_id", 1), ("stock_quantity", 1)])
        await products.create_index([("name", "text"), ("tags", "text")])
        await products.create_index("product_id", unique=True)

        # Stores collection indexes
        stores = cls.database.stores
        await stores.create_index([("address.coordinates", "2dsphere")])
        await stores.create_index("status")
        await stores.create_index("store_id", unique=True)

        # Orders collection indexes
        orders = cls.database.orders
        await orders.create_index([("user_id", 1), ("created_at", -1)])
        await orders.create_index([("store_id", 1), ("status", 1)])
        await orders.create_index("order_id", unique=True)

        # Users collection indexes
        users = cls.database.users
        await users.create_index("user_id", unique=True)
        await users.create_index("phone", unique=True)
        await users.create_index("email", unique=True, sparse=True, name="email_sparse_unique")

        logger.info("MongoDB indexes created successfully")

    @classmethod
    def get_collection(cls, collection_name: str):
        """Get a specific collection"""
        if cls.database is None:
            raise RuntimeError("Database not connected")
        return cls.database[collection_name]


async def get_database() -> AsyncIOMotorDatabase:
    """Dependency to get database instance"""
    if MongoDB.database is None:
        await MongoDB.connect()
    return MongoDB.database
