"""
Check My Dukkan store in database
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

async def check_store():
    mongodb_uri = os.getenv('MONGODB_URI')
    client = AsyncIOMotorClient(mongodb_uri)
    db = client['nukkadmart']
    
    print("Searching for stores with 'Dukkan' in name...")
    stores = await db.stores.find({"name": {"$regex": "Dukkan", "$options": "i"}}).to_list(10)
    
    if not stores:
        print("❌ No stores found with 'Dukkan' in name")
        print("\nSearching for all non-demo stores...")
        all_stores = await db.stores.find({
            "$or": [
                {"is_demo": {"$exists": False}},
                {"is_demo": False}
            ]
        }).to_list(10)
        print(f"Found {len(all_stores)} non-demo stores:")
        for s in all_stores:
            print(f"  - {s.get('name')} (ID: {s.get('store_id')}, Status: {s.get('status')})")
    else:
        for store in stores:
            print(f"\n{'='*60}")
            print(f"Store: {store.get('name')}")
            print(f"Store ID: {store.get('store_id')}")
            print(f"Status: {store.get('status')}")
            print(f"Is Demo: {store.get('is_demo', 'Not set')}")
            
            address = store.get('address', {})
            print(f"\nAddress: {address.get('street', 'N/A')}, {address.get('city', 'N/A')}")
            
            coords = address.get('coordinates', {})
            if coords.get('type') == 'Point':
                lng, lat = coords.get('coordinates', [0, 0])
                print(f"Coordinates: lat={lat}, lng={lng}")
            else:
                lat = coords.get('lat', 0)
                lng = coords.get('lng', 0)
                print(f"Coordinates: lat={lat}, lng={lng}")
            
            if lat == 0 and lng == 0:
                print("⚠️  WARNING: Store has no coordinates set!")
            
            print(f"\nTotal Products: {store.get('total_products', 0)}")
            print(f"Rating: {store.get('rating', 'N/A')}")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(check_store())
