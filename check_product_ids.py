"""
Check product IDs in database to verify they have product_id field
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

async def check_products():
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DB_NAME]
    
    print("Checking products in DEMO_STORE_1...")
    products = await db.products.find({"store_id": "DEMO_STORE_1"}).limit(5).to_list(length=5)
    
    for p in products:
        print(f"\nProduct: {p.get('name')}")
        print(f"  _id: {p.get('_id')}")
        print(f"  product_id: {p.get('product_id')}")
        print(f"  Has product_id field: {'product_id' in p}")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(check_products())
