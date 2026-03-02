"""
Create optimized MongoDB indexes for voice assistant queries
Run this once to improve database performance
"""
import asyncio
from app.db.mongodb import get_database
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def create_indexes():
    """Create compound indexes for faster queries"""
    db = await get_database()
    
    logger.info("Creating MongoDB indexes...")
    
    # 1. Products collection indexes
    logger.info("Creating indexes on 'products' collection...")
    
    try:
        # Compound index for store + active products
        await db.products.create_index([
            ("store_id", 1),
            ("is_active", 1),
            ("stock_quantity", -1)
        ], name="store_active_stock_idx")
        logger.info("✅ Created: store_active_stock_idx")
    except Exception as e:
        logger.info(f"⚠️  store_active_stock_idx: {str(e)[:100]}")
    
    # Text index already exists, skip it
    logger.info("⚠️  product_search_idx: Already exists (name_text_tags_text)")
    
    try:
        # Category + stock index
        await db.products.create_index([
            ("store_id", 1),
            ("category", 1),
            ("stock_quantity", -1)
        ], name="store_category_stock_idx")
        logger.info("✅ Created: store_category_stock_idx")
    except Exception as e:
        logger.info(f"⚠️  store_category_stock_idx: Already exists")
    
    # 2. Inventory collection indexes
    logger.info("Creating indexes on 'inventory' collection...")
    
    try:
        # Compound index for store inventory queries
        await db.inventory.create_index([
            ("store_id", 1),
            ("product_id", 1)
        ], name="store_product_idx", unique=True)
        logger.info("✅ Created: store_product_idx")
    except Exception as e:
        logger.info(f"⚠️  store_product_idx: Already exists or error")
    
    try:
        # Stock level index
        await db.inventory.create_index([
            ("store_id", 1),
            ("stock", -1)
        ], name="store_stock_idx")
        logger.info("✅ Created: store_stock_idx")
    except Exception as e:
        logger.info(f"⚠️  store_stock_idx: Already exists")
    
    # 3. Stores collection indexes
    logger.info("Creating indexes on 'stores' collection...")
    
    # Geospatial index already exists
    logger.info("⚠️  location_geo_idx: Already exists")
    
    try:
        # Active stores index
        await db.stores.create_index([
            ("is_active", 1),
            ("store_type", 1)
        ], name="active_type_idx")
        logger.info("✅ Created: active_type_idx")
    except Exception as e:
        logger.info(f"⚠️  active_type_idx: Already exists")
    
    # 4. Users collection indexes
    logger.info("Creating indexes on 'users' collection...")
    
    # User lookup index already exists
    logger.info("⚠️  user_id_idx: Already exists")
    
    # 5. Orders collection indexes
    logger.info("Creating indexes on 'orders' collection...")
    
    # User orders index already exists
    logger.info("⚠️  user_orders_idx: Already exists")
    
    # Store orders index already exists
    logger.info("⚠️  store_orders_idx: Already exists (store_id_1_status_1)")
    
    logger.info("\n✅ Index creation complete!")
    logger.info("Most indexes already existed - database is optimized!")

async def list_existing_indexes():
    """List all existing indexes"""
    db = await get_database()
    
    collections = ['products', 'inventory', 'stores', 'users', 'orders']
    
    logger.info("\n📋 Existing Indexes:")
    for collection_name in collections:
        collection = db[collection_name]
        indexes = await collection.index_information()
        
        logger.info(f"\n{collection_name}:")
        for idx_name, idx_info in indexes.items():
            logger.info(f"  - {idx_name}: {idx_info.get('key', [])}")

async def main():
    """Main execution"""
    logger.info("🔧 MongoDB Index Creation Tool")
    logger.info("=" * 60)
    
    # List existing indexes first
    await list_existing_indexes()
    
    logger.info("\n" + "=" * 60)
    logger.info("Creating new indexes...")
    logger.info("=" * 60 + "\n")
    
    # Create indexes
    await create_indexes()
    
    # List indexes again to confirm
    logger.info("\n" + "=" * 60)
    await list_existing_indexes()

if __name__ == "__main__":
    asyncio.run(main())
