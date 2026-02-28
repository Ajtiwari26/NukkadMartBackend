"""
Quick script to seed test store with location and products
"""
from pymongo import MongoClient
from bson import ObjectId

# Connect to MongoDB
client = MongoClient('mongodb+srv://nukkadmart:Ajtiwari23@nukkadmart.0imveqj.mongodb.net/?appName=NukkadMart')
db = client['nukkadmart']

# Your location from logs: 23.1254938, 77.4900117 (Bhopal)
test_location = {
    "type": "Point",
    "coordinates": [77.4900117, 23.1254938]  # [longitude, latitude]
}

# Update existing store or create new one
store_id = "STORE_E2F05A"

# Update store with location and active status
result = db.stores.update_one(
    {"store_id": store_id},
    {
        "$set": {
            "location": test_location,
            "is_active": True,
            "name": "Test Kirana Store",
            "rating": 4.5
        }
    },
    upsert=True
)

print(f"✓ Updated store {store_id} with location")

# Check if products exist for this store
product_count = db.products.count_documents({"store_id": store_id, "is_active": True})
print(f"✓ Store has {product_count} active products")

# Verify
store = db.stores.find_one({"store_id": store_id})
print(f"\nStore details:")
print(f"  Name: {store.get('name')}")
print(f"  Location: {store.get('location')}")
print(f"  Active: {store.get('is_active')}")

client.close()
print("\n✅ Database seeded successfully!")
