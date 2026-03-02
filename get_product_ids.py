"""
Get product IDs for testing cart actions
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

async def get_product_ids():
    """Get product IDs from database"""
    
    mongodb_uri = os.getenv('MONGODB_URL')
    client = AsyncIOMotorClient(mongodb_uri)
    db = client['nukkadmart']
    
    print("📦 Products with IDs:\n")
    
    products = await db.products.find({"store_id": "STORE_E2F05A"}).to_list(length=100)
    
    for p in products:
        print(f"ID: {str(p['_id'])} | {p.get('name')} ({p.get('brand', 'No Brand')}) - ₹{p.get('price')}")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(get_product_ids())
