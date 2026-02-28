"""
Link existing products to the Dukaan store
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

async def link_products():
    """Link products to Dukaan store"""
    
    # Connect to MongoDB
    mongodb_uri = os.getenv('MONGODB_URL')
    client = AsyncIOMotorClient(mongodb_uri)
    db = client['nukkadmart']
    
    print("🔗 Linking products to Dukaan store...")
    
    # Find store
    store = await db.stores.find_one({"name": "Dukaan"})
    if not store:
        print("❌ Store 'Dukaan' not found")
        client.close()
        return
    
    store_id = store['store_id']  # Use custom store_id, NOT MongoDB _id
    print(f"✅ Found Store: {store.get('name')} (ID: {store_id})")
    
    # Update all products to link to this store
    result = await db.products.update_many(
        {},  # All products
        {"$set": {"store_id": store_id, "is_active": True}}
    )
    
    print(f"✅ Updated {result.modified_count} products with store_id")
    
    # Fix products missing product_id (from seed_smart_products.py)
    import uuid
    products_without_id = await db.products.find({"product_id": {"$exists": False}}).to_list(length=1000)
    for p in products_without_id:
        product_id = f"PROD_{uuid.uuid4().hex[:8].upper()}"
        await db.products.update_one(
            {"_id": p["_id"]},
            {"$set": {"product_id": product_id}}
        )
    if products_without_id:
        print(f"✅ Added product_id to {len(products_without_id)} products")
    
    # Fix products using 'stock' instead of 'stock_quantity' (from seed_smart_products.py)
    products_with_stock = await db.products.find({
        "stock": {"$exists": True},
        "stock_quantity": {"$exists": False}
    }).to_list(length=1000)
    for p in products_with_stock:
        await db.products.update_one(
            {"_id": p["_id"]},
            {"$set": {"stock_quantity": p.get("stock", 0)}}
        )
    if products_with_stock:
        print(f"✅ Migrated 'stock' -> 'stock_quantity' for {len(products_with_stock)} products")
    
    # Fix products missing mrp (set mrp = price)
    await db.products.update_many(
        {"mrp": {"$exists": False}},
        [{"$set": {"mrp": "$price"}}]
    )
    
    # Verify
    products = await db.products.find({"store_id": store_id}).to_list(length=100)
    print(f"✅ Store now has {len(products)} products")
    
    if products:
        print("\n📦 Sample Products:")
        for p in products[:10]:
            print(f"   - {p.get('name')} ({p.get('brand', 'Local')}) - ₹{p.get('price')} - Stock: {p.get('stock_quantity', p.get('stock', 0))}")
    
    print(f"\n🎉 Products successfully linked to store!")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(link_products())
