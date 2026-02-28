"""
Update stock levels for products
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

async def update_stock():
    """Update stock levels"""
    
    # Connect to MongoDB
    mongodb_uri = os.getenv('MONGODB_URL')
    client = AsyncIOMotorClient(mongodb_uri)
    db = client['nukkadmart']
    
    print("📦 Updating stock levels...")
    
    # Update all products to have stock
    result = await db.products.update_many(
        {},  # All products
        {"$set": {"stock": 50}}  # Set to 50
    )
    
    print(f"✅ Updated {result.modified_count} products to have stock = 50")
    
    # Verify
    store = await db.stores.find_one({"name": "Dukaan"})
    store_id = str(store['_id'])
    
    products = await db.products.find({"store_id": store_id, "stock": {"$gt": 0}}).to_list(length=100)
    print(f"✅ Store now has {len(products)} products in stock")
    
    if products:
        print("\n📦 Products with Stock:")
        for p in products[:15]:
            print(f"   - {p.get('name')} ({p.get('brand', 'Local')}) - ₹{p.get('price')} - Stock: {p.get('stock')}")
    
    print(f"\n🎉 Stock updated successfully!")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(update_stock())
