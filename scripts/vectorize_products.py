"""
Product Vectorization Script
Generates Titan Text Embeddings V2 vectors for all products in MongoDB
and stores them as `name_vector` field for semantic search.

Usage:
  cd NukkadBackend
  source venv/bin/activate
  python -m scripts.vectorize_products [--store-id DEMO_STORE_1] [--all]
"""
import asyncio
import argparse
import sys
import os
import logging

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from app.services.embedding_service import get_embedding_service
from app.services.search_service import resolve_aliases

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def vectorize_products(store_id: str = None):
    """Generate and store embeddings for products."""
    
    # Connect to MongoDB
    mongo_url = os.getenv('MONGODB_URL', 'mongodb://localhost:27017')
    db_name = os.getenv('MONGODB_DATABASE', 'nukkadmart')
    
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    products = db.products
    
    # Build query
    query = {"is_active": True}
    if store_id:
        query["store_id"] = store_id
    
    # Count products
    total = await products.count_documents(query)
    logger.info(f"Found {total} products to vectorize" + (f" for store {store_id}" if store_id else ""))
    
    if total == 0:
        logger.warning("No products found. Check your store_id or database connection.")
        return
    
    # Initialize embedding service
    embed_service = get_embedding_service()
    
    # Process products
    success = 0
    failed = 0
    skipped = 0
    
    cursor = products.find(query)
    async for product in cursor:
        pid = product.get("product_id", "?")
        name = product.get("name", "")
        brand = product.get("brand", "")
        category = product.get("category", "")
        
        # Skip if already has vector
        if product.get("name_vector") and len(product["name_vector"]) > 0:
            skipped += 1
            continue
        
        if not name:
            failed += 1
            continue
        
        # Build rich text for embedding (name + brand + aliases)
        aliases = resolve_aliases(name)
        embed_text = f"{name} {brand} {' '.join(aliases)} {category}".strip()
        
        # Generate embedding
        vector = embed_service.generate_embedding(embed_text)
        
        if vector:
            # Store vector in MongoDB
            await products.update_one(
                {"product_id": pid},
                {"$set": {"name_vector": vector}}
            )
            success += 1
            if success % 10 == 0:
                logger.info(f"  ✅ Vectorized {success}/{total}: {name}")
        else:
            failed += 1
            logger.warning(f"  ❌ Failed: {name} ({pid})")
    
    logger.info(f"\n{'='*50}")
    logger.info(f"Vectorization complete!")
    logger.info(f"  ✅ Success: {success}")
    logger.info(f"  ⏭️  Skipped (already had vector): {skipped}")
    logger.info(f"  ❌ Failed: {failed}")
    logger.info(f"  📊 Total: {total}")
    
    client.close()


async def clear_vectors(store_id: str = None):
    """Remove all name_vector fields (for re-vectorization)."""
    mongo_url = os.getenv('MONGODB_URL', 'mongodb://localhost:27017')
    db_name = os.getenv('MONGODB_DATABASE', 'nukkadmart')
    
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    
    query = {}
    if store_id:
        query["store_id"] = store_id
    
    result = await db.products.update_many(query, {"$unset": {"name_vector": ""}})
    logger.info(f"Cleared vectors from {result.modified_count} products")
    client.close()


if __name__ == "__main__":
    # Load .env
    from dotenv import load_dotenv
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="Vectorize products for semantic search")
    parser.add_argument("--store-id", help="Only vectorize products for this store")
    parser.add_argument("--all", action="store_true", help="Vectorize all products")
    parser.add_argument("--clear", action="store_true", help="Clear existing vectors first")
    parser.add_argument("--force", action="store_true", help="Re-vectorize even if vector exists")
    
    args = parser.parse_args()
    
    if not args.store_id and not args.all:
        # Default: vectorize all demo stores
        logger.info("No --store-id or --all specified. Vectorizing all demo stores.")
        async def run():
            if args.clear:
                await clear_vectors()
            for sid in ['DEMO_STORE_1', 'DEMO_STORE_2', 'DEMO_STORE_3']:
                await vectorize_products(sid)
        asyncio.run(run())
    else:
        async def run():
            if args.clear:
                await clear_vectors(args.store_id)
            await vectorize_products(args.store_id if not args.all else None)
        asyncio.run(run())
