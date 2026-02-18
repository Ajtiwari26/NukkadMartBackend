"""Seed MongoDB Atlas with test data"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime

MONGODB_URL = "mongodb+srv://nukkadmart:Ajtiwari23@nukkadmart.0imveqj.mongodb.net/?appName=NukkadMart"

async def seed_data():
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client.nukkadmart

    # Clear existing data
    await db.stores.delete_many({})
    await db.products.delete_many({})
    await db.users.delete_many({})

    # Insert sample store
    store = {
        "store_id": "STORE_123",
        "name": "Sharma Kirana Store",
        "owner_name": "Rajesh Sharma",
        "phone": "+91-9876543210",
        "email": "sharma.kirana@example.com",
        "address": {
            "street": "123 MG Road",
            "city": "Bangalore",
            "state": "Karnataka",
            "pincode": "560001",
            "coordinates": {
                "type": "Point",
                "coordinates": [77.5946, 12.9716]
            }
        },
        "google_maps_url": "https://maps.google.com/?cid=123456789",
        "settings": {
            "max_discount_percent": 15,
            "delivery_radius_km": 5,
            "min_order_value": 100,
            "accepts_takeaway": True,
            "accepts_delivery": True
        },
        "status": "ACTIVE",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    await db.stores.insert_one(store)
    print("Store inserted")

    # Insert sample products
    products = [
        {
            "product_id": "PROD_001",
            "store_id": "STORE_123",
            "name": "Tata Salt",
            "category": "Grocery",
            "brand": "Tata",
            "price": 20.00,
            "mrp": 22.00,
            "unit": "1kg",
            "stock_quantity": 150,
            "tags": ["salt", "cooking"],
            "created_at": datetime.utcnow()
        },
        {
            "product_id": "PROD_002",
            "store_id": "STORE_123",
            "name": "India Gate Basmati Rice",
            "category": "Grocery",
            "brand": "India Gate",
            "price": 180.00,
            "mrp": 200.00,
            "unit": "5kg",
            "stock_quantity": 45,
            "tags": ["rice", "basmati"],
            "created_at": datetime.utcnow()
        },
        {
            "product_id": "PROD_003",
            "store_id": "STORE_123",
            "name": "Amul Butter",
            "category": "Dairy",
            "brand": "Amul",
            "price": 56.00,
            "mrp": 58.00,
            "unit": "100g",
            "stock_quantity": 80,
            "tags": ["butter", "dairy"],
            "created_at": datetime.utcnow()
        },
        {
            "product_id": "PROD_004",
            "store_id": "STORE_123",
            "name": "Toor Dal",
            "category": "Grocery",
            "brand": "Local",
            "price": 140.00,
            "mrp": 150.00,
            "unit": "1kg",
            "stock_quantity": 60,
            "tags": ["dal", "pulses"],
            "created_at": datetime.utcnow()
        },
        {
            "product_id": "PROD_005",
            "store_id": "STORE_123",
            "name": "Nandini Milk",
            "category": "Dairy",
            "brand": "Nandini",
            "price": 27.00,
            "mrp": 27.00,
            "unit": "500ml",
            "stock_quantity": 100,
            "tags": ["milk", "dairy"],
            "created_at": datetime.utcnow()
        }
    ]
    await db.products.insert_many(products)
    print("Products inserted")

    # Create indexes
    await db.stores.create_index("store_id", unique=True)
    await db.stores.create_index([("address.coordinates", "2dsphere")])
    await db.products.create_index("product_id", unique=True)
    await db.products.create_index([("store_id", 1), ("category", 1)])
    print("Indexes created")

    client.close()
    print("Database seeded successfully!")

if __name__ == "__main__":
    asyncio.run(seed_data())
