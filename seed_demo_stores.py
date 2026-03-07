"""
Seed 3 Demo Stores with full inventory for hackathon demo mode.
Each store gets ~25 products with price, unit/weight, brand, category, tags.
Run: python seed_demo_stores.py
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import os
import uuid
from dotenv import load_dotenv

load_dotenv()

# ============ DEMO PRODUCTS (detailed for AI voice/scan testing) ============

DEMO_PRODUCTS = [
    # ---- Groceries / Staples (sold by weight) ----
    {"name": "Basmati Rice (1kg)", "brand": "India Gate", "price": 180, "mrp": 199, "unit": "kg", "stock_quantity": 50, "category": "Groceries", "tags": ["rice", "chawal", "basmati"]},
    {"name": "Basmati Rice (500g)", "brand": "India Gate", "price": 95, "mrp": 105, "unit": "g", "stock_quantity": 30, "category": "Groceries", "tags": ["rice", "chawal", "basmati"]},
    {"name": "Regular Rice (1kg)", "brand": "Local", "price": 40, "mrp": 40, "unit": "kg", "stock_quantity": 100, "category": "Groceries", "tags": ["rice", "chawal"]},
    {"name": "Aashirvaad Atta (1kg)", "brand": "Aashirvaad", "price": 40, "mrp": 45, "unit": "kg", "stock_quantity": 70, "category": "Groceries", "tags": ["atta", "flour", "wheat"]},
    {"name": "Aashirvaad Atta (5kg)", "brand": "Aashirvaad", "price": 190, "mrp": 210, "unit": "kg", "stock_quantity": 20, "category": "Groceries", "tags": ["atta", "flour", "wheat"]},
    {"name": "Toor Dal (1kg)", "brand": "Tata Sampann", "price": 120, "mrp": 135, "unit": "kg", "stock_quantity": 45, "category": "Groceries", "tags": ["dal", "lentils", "toor"]},
    {"name": "Moong Dal (1kg)", "brand": "Local", "price": 110, "mrp": 110, "unit": "kg", "stock_quantity": 40, "category": "Groceries", "tags": ["dal", "lentils", "moong"]},
    {"name": "Tata Sugar (1kg)", "brand": "Tata", "price": 45, "mrp": 48, "unit": "kg", "stock_quantity": 60, "category": "Groceries", "tags": ["sugar", "chini"]},
    {"name": "Tata Salt (1kg)", "brand": "Tata", "price": 28, "mrp": 28, "unit": "kg", "stock_quantity": 80, "category": "Groceries", "tags": ["salt", "namak", "iodized"]},
    {"name": "Jaggery Gur (500g)", "brand": "Local", "price": 60, "mrp": 65, "unit": "g", "stock_quantity": 30, "category": "Groceries", "tags": ["jaggery", "gur", "sweetener"]},

    # ---- Packaged / Instant Food (sold per piece) ----
    {"name": "Maggi Masala Noodles (70g)", "brand": "Nestle", "price": 14, "mrp": 14, "unit": "packet", "stock_quantity": 120, "category": "Instant Food", "tags": ["noodles", "maggi", "instant"]},
    {"name": "Yippee Noodles (60g)", "brand": "Sunfeast", "price": 10, "mrp": 10, "unit": "packet", "stock_quantity": 80, "category": "Instant Food", "tags": ["noodles", "instant", "yippee"]},
    {"name": "Top Ramen Curry (70g)", "brand": "Top Ramen", "price": 12, "mrp": 14, "unit": "packet", "stock_quantity": 50, "category": "Instant Food", "tags": ["noodles", "instant", "ramen"]},

    # ---- Dairy ----
    {"name": "Amul Taza Milk (500ml)", "brand": "Amul", "price": 25, "mrp": 25, "unit": "packet", "stock_quantity": 30, "category": "Dairy", "tags": ["milk", "doodh", "dairy"]},
    {"name": "Amul Taza Milk (1L)", "brand": "Amul", "price": 68, "mrp": 68, "unit": "packet", "stock_quantity": 40, "category": "Dairy", "tags": ["milk", "doodh", "dairy"]},
    {"name": "Amul Butter (100g)", "brand": "Amul", "price": 56, "mrp": 57, "unit": "packet", "stock_quantity": 25, "category": "Dairy", "tags": ["butter", "makhan", "dairy"]},
    {"name": "Mother Dairy Curd (400g)", "brand": "Mother Dairy", "price": 30, "mrp": 30, "unit": "piece", "stock_quantity": 20, "category": "Dairy", "tags": ["curd", "dahi", "dairy"]},

    # ---- Beverages ----
    {"name": "Tata Tea Gold (500g)", "brand": "Tata", "price": 180, "mrp": 195, "unit": "packet", "stock_quantity": 40, "category": "Beverages", "tags": ["tea", "chai", "chai patti"]},
    {"name": "Nescafe Classic Coffee (50g)", "brand": "Nescafe", "price": 95, "mrp": 100, "unit": "bottle", "stock_quantity": 35, "category": "Beverages", "tags": ["coffee", "instant coffee"]},
    {"name": "Bisleri Water (1L)", "brand": "Bisleri", "price": 20, "mrp": 20, "unit": "bottle", "stock_quantity": 100, "category": "Beverages", "tags": ["water", "paani", "mineral water"]},

    # ---- Household ----
    {"name": "Surf Excel Detergent (1kg)", "brand": "Surf Excel", "price": 180, "mrp": 199, "unit": "box", "stock_quantity": 25, "category": "Household", "tags": ["detergent", "washing powder", "surf"]},
    {"name": "Vim Dishwash Bar (100g)", "brand": "Vim", "price": 10, "mrp": 10, "unit": "piece", "stock_quantity": 60, "category": "Household", "tags": ["dishwash", "bartan", "cleaning"]},
    {"name": "Clinic Plus Shampoo (6ml)", "brand": "Clinic Plus", "price": 3, "mrp": 3, "unit": "packet", "stock_quantity": 200, "category": "Household", "tags": ["shampoo", "hair"]},

    # ---- Spices / Masala ----
    {"name": "MDH Chana Masala (100g)", "brand": "MDH", "price": 68, "mrp": 75, "unit": "box", "stock_quantity": 35, "category": "Spices", "tags": ["masala", "spice", "chana"]},
    {"name": "Everest Turmeric Powder (100g)", "brand": "Everest", "price": 42, "mrp": 45, "unit": "packet", "stock_quantity": 50, "category": "Spices", "tags": ["haldi", "turmeric", "spice"]},
    {"name": "Red Chilli Powder (100g)", "brand": "Everest", "price": 55, "mrp": 58, "unit": "packet", "stock_quantity": 40, "category": "Spices", "tags": ["mirchi", "chilli", "lal mirch", "spice"]},

    # ---- Snacks ----
    {"name": "Lays Classic Salted (52g)", "brand": "Lays", "price": 20, "mrp": 20, "unit": "packet", "stock_quantity": 60, "category": "Snacks", "tags": ["chips", "snack", "lays"]},
    {"name": "Parle-G Biscuits (80g)", "brand": "Parle", "price": 10, "mrp": 10, "unit": "packet", "stock_quantity": 100, "category": "Snacks", "tags": ["biscuit", "cookies", "parle"]},

    # ---- Oil ----
    {"name": "Fortune Sunflower Oil (1L)", "brand": "Fortune", "price": 155, "mrp": 170, "unit": "packet", "stock_quantity": 30, "category": "Groceries", "tags": ["oil", "tel", "cooking oil", "sunflower"]},
    {"name": "Saffola Gold Oil (1L)", "brand": "Saffola", "price": 185, "mrp": 199, "unit": "packet", "stock_quantity": 20, "category": "Groceries", "tags": ["oil", "tel", "cooking oil", "saffola"]},
]


# ============ DEMO STORES ============

DEMO_STORES = [
    {
        "store_id": "DEMO_STORE_1",
        "name": "TestShop 1 - Kirana Corner",
        "description": "Demo grocery store for hackathon",
    },
    {
        "store_id": "DEMO_STORE_2",
        "name": "TestShop 2 - Daily Needs",
        "description": "Demo daily essentials store",
    },
    {
        "store_id": "DEMO_STORE_3",
        "name": "TestShop 3 - Fresh Mart",
        "description": "Demo fresh & groceries store",
    },
]


async def seed_demo_data():
    """Seed demo stores and products into MongoDB."""
    mongodb_uri = os.getenv('MONGODB_URI', 'mongodb+srv://nukkadmart:Ajtiwari23@nukkadmart.0imveqj.mongodb.net/?appName=NukkadMart')
    client = AsyncIOMotorClient(mongodb_uri)
    db = client['nukkadmart']

    print("🧪 Seeding DEMO stores and products...")

    # ---- 1. Clean up old demo data ----
    del_stores = await db.stores.delete_many({"is_demo": True})
    del_products = await db.products.delete_many({"is_demo": True})
    print(f"   Cleaned {del_stores.deleted_count} old demo stores, {del_products.deleted_count} old demo products")

    # ---- 2. Insert Demo Stores ----
    now = datetime.utcnow()
    for store_info in DEMO_STORES:
        store_doc = {
            "store_id": store_info["store_id"],
            "name": store_info["name"],
            "owner_name": "Demo Owner",
            "phone": f"0000000{DEMO_STORES.index(store_info) + 1:03d}",
            "email": None,
            "is_demo": True,
            "address": {
                "street": "Demo Street",
                "city": "Demo City",
                "state": "Madhya Pradesh",
                "pincode": "462001",
                "coordinates": {
                    "type": "Point",
                    "coordinates": [77.4126, 23.2599]  # Bhopal default
                }
            },
            "operating_hours": {
                "monday": {"open": "00:00", "close": "23:59"},
                "tuesday": {"open": "00:00", "close": "23:59"},
                "wednesday": {"open": "00:00", "close": "23:59"},
                "thursday": {"open": "00:00", "close": "23:59"},
                "friday": {"open": "00:00", "close": "23:59"},
                "saturday": {"open": "00:00", "close": "23:59"},
                "sunday": {"open": "00:00", "close": "23:59"},
            },
            "settings": {
                "max_discount_percent": 15,
                "delivery_radius_km": 999,  # Always deliver in demo
                "min_order_value": 0,  # No minimum in demo
                "accepts_takeaway": True,
                "accepts_delivery": True,
                "udhaar_enabled": False,
                "preparation_time_minutes": 15,
                "estimated_delivery_time_minutes": 30,
            },
            "status": "ACTIVE",
            "total_products": len(DEMO_PRODUCTS),
            "rating": 4.5,
            "created_at": now,
            "updated_at": now,
        }
        await db.stores.insert_one(store_doc)
        print(f"   ✅ Created store: {store_info['name']}")

    # ---- 3. Insert Products for each store ----
    all_products = []
    
    # Distribute products among stores
    # Store 1 gets first 10
    # Store 2 gets next 10
    # Store 3 gets the rest
    
    products_store_1 = DEMO_PRODUCTS[:10]
    products_store_2 = DEMO_PRODUCTS[10:20]
    products_store_3 = DEMO_PRODUCTS[20:]
    
    store_product_map = {
        "DEMO_STORE_1": products_store_1,
        "DEMO_STORE_2": products_store_2,
        "DEMO_STORE_3": products_store_3,
    }
    
    for store_info in DEMO_STORES:
        store_id = store_info["store_id"]
        store_products = store_product_map.get(store_id, [])
        for prod in store_products:
            product_doc = {
                "product_id": f"PROD_{uuid.uuid4().hex[:8].upper()}",
                "store_id": store_id,
                "name": prod["name"],
                "brand": prod["brand"],
                "price": prod["price"],
                "mrp": prod["mrp"],
                "unit": prod["unit"],
                "stock_quantity": prod["stock_quantity"],
                "category": prod["category"],
                "tags": prod["tags"],
                "is_active": True,
                "is_available": True,  # CRITICAL: Required for match_smart_cart query
                "is_demo": True,
                "image_url": None,
                "created_at": now,
                "updated_at": now,
            }
            all_products.append(product_doc)

    result = await db.products.insert_many(all_products)
    print(f"   ✅ Inserted {len(result.inserted_ids)} products across {len(DEMO_STORES)} stores")

    # ---- 4. Create indexes ----
    await db.products.create_index([("name", "text"), ("tags", "text")])
    await db.products.create_index("store_id")
    await db.products.create_index("category")
    await db.stores.create_index([("address.coordinates", "2dsphere")])

    # ---- 5. Summary ----
    print("\n📊 Demo Inventory Summary:")
    categories = {}
    for p in DEMO_PRODUCTS:
        cat = p["category"]
        categories[cat] = categories.get(cat, 0) + 1
    for cat, count in sorted(categories.items()):
        print(f"   {cat}: {count} products")

    print(f"\n🎉 Demo seeding complete!")
    print(f"   Stores: {len(DEMO_STORES)}")
    print(f"   Products per store: {len(DEMO_PRODUCTS)}")
    print(f"   Total products: {len(all_products)}")

    client.close()


if __name__ == "__main__":
    asyncio.run(seed_demo_data())
