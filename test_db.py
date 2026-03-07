import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client.nukkadmart
    
    # Check DEMO_STORE_1 products
    products = await db.products.find({"store_id": "DEMO_STORE_1"}).to_list(100)
    print(f"Total DEMO_STORE_1 products: {len(products)}")
    print("DEMO_STORE_1 Product names:")
    for p in products:
        print(f" - {p.get('name')} (Brand: {p.get('brand')}) [Available: {p.get('is_available')}, Stock: {p.get('stock_quantity')}]")

if __name__ == "__main__":
    asyncio.run(main())
