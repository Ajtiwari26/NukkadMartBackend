"""
Check store inventory in database
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
from bson import ObjectId

load_dotenv()

async def check_inventory():
    """Check store and inventory"""
    
    # Connect to MongoDB
    mongodb_uri = os.getenv('MONGODB_URL')
    client = AsyncIOMotorClient(mongodb_uri)
    db = client['nukkadmart']
    
    print("🔍 Checking Store 'Dukaan'...")
    
    # Find store
    store = await db.stores.find_one({"name": "Dukaan"})
    if store:
        store_id = store['store_id']  # Use custom store_id, NOT MongoDB _id
        print(f"\n✅ Found Store:")
        print(f"   ID: {store_id}")
        print(f"   Name: {store.get('name')}")
        print(f"   Owner: {store.get('owner_name')}")
        print(f"   Active: {store.get('is_active')}")
        print(f"   Location: {store.get('location')}")
        
        # Check products with this store_id
        print(f"\n🔍 Checking products with store_id = '{store_id}'...")
        products = await db.products.find({"store_id": store_id}).to_list(length=100)
        print(f"   Found {len(products)} products")
        
        if products:
            print("\n📦 Products:")
            for p in products[:10]:  # Show first 10
                print(f"   - {p.get('name')} ({p.get('brand')}) - ₹{p.get('price')} - Stock: {p.get('stock', 0)}")
        
        # Check inventory collection
        print(f"\n🔍 Checking inventory collection...")
        inventory = await db.inventory.find({"store_id": store_id}).to_list(length=100)
        print(f"   Found {len(inventory)} inventory items")
        
        if inventory:
            print("\n📦 Inventory:")
            for inv in inventory[:10]:  # Show first 10
                product_id = inv.get('product_id')
                product = await db.products.find_one({"_id": ObjectId(product_id)})
                if product:
                    print(f"   - {product.get('name')} - Stock: {inv.get('stock', 0)}")
        
        # Check all products (without store_id filter)
        print(f"\n🔍 Checking ALL products in database...")
        all_products = await db.products.find({}).to_list(length=10)
        print(f"   Total products in DB: {await db.products.count_documents({})}")
        
        if all_products:
            print("\n📦 Sample Products (first 10):")
            for p in all_products:
                print(f"   - {p.get('name')} ({p.get('brand')}) - store_id: {p.get('store_id', 'NOT SET')}")
        
    else:
        print("❌ Store 'Dukaan' not found")
        
        # List all stores
        print("\n📋 All stores in database:")
        stores = await db.stores.find({}).to_list(length=10)
        for s in stores:
            print(f"   - {s.get('name')} (ID: {str(s['_id'])})")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(check_inventory())
