"""
Clean up orphaned products (products from deleted stores)
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

async def cleanup_orphaned_products():
    """Remove products that belong to non-existent stores"""
    
    # Connect to MongoDB
    mongodb_uri = os.getenv('MONGODB_URL')
    client = AsyncIOMotorClient(mongodb_uri)
    db = client['nukkadmart']
    
    print("🧹 Cleaning up orphaned products...")
    
    # Get all unique store_ids from products
    product_store_ids = await db.products.distinct("store_id")
    print(f"Found {len(product_store_ids)} unique store_ids in products")
    
    # Get all existing store IDs
    stores = await db.stores.find({}, {"_id": 1}).to_list(length=1000)
    existing_store_ids = {str(store["_id"]) for store in stores}
    print(f"Found {len(existing_store_ids)} existing stores")
    
    # Find orphaned products
    orphaned_store_ids = set(product_store_ids) - existing_store_ids
    
    if orphaned_store_ids:
        print(f"\n❌ Found {len(orphaned_store_ids)} orphaned store IDs:")
        for store_id in orphaned_store_ids:
            count = await db.products.count_documents({"store_id": store_id})
            print(f"   - {store_id}: {count} products")
        
        # Delete orphaned products
        result = await db.products.delete_many({"store_id": {"$in": list(orphaned_store_ids)}})
        print(f"\n✅ Deleted {result.deleted_count} orphaned products")
    else:
        print("\n✅ No orphaned products found")
    
    # Show remaining products
    remaining = await db.products.count_documents({})
    print(f"\n📦 Remaining products: {remaining}")
    
    if remaining > 0:
        print("\n📋 Products by store:")
        for store_id in existing_store_ids:
            count = await db.products.count_documents({"store_id": store_id})
            if count > 0:
                store = await db.stores.find_one({"_id": store_id})
                store_name = store.get("name", "Unknown") if store else "Unknown"
                print(f"   - {store_name} ({store_id}): {count} products")
    
    print(f"\n🎉 Cleanup complete!")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(cleanup_orphaned_products())
