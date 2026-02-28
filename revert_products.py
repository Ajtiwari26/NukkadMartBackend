"""
Revert products back to original store_ids
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

async def revert_products():
    """Revert products to original state"""
    
    # Connect to MongoDB
    mongodb_uri = os.getenv('MONGODB_URL')
    client = AsyncIOMotorClient(mongodb_uri)
    db = client['nukkadmart']
    
    print("⏪ Reverting products to original store_ids...")
    
    # Get Dukaan store ID
    store = await db.stores.find_one({"name": "Dukaan"})
    if store:
        dukaan_store_id = str(store['_id'])
        
        # Find products that were changed (have Dukaan's store_id)
        products = await db.products.find({"store_id": dukaan_store_id}).to_list(length=100)
        print(f"Found {len(products)} products linked to Dukaan")
        
        # Revert them back
        # Products with brand names go to STORE_123
        # Products without brands go to STORE_19CF2B
        
        for product in products:
            if product.get('brand') and product.get('brand') not in ['', 'Local']:
                # Has brand -> STORE_123
                await db.products.update_one(
                    {"_id": product['_id']},
                    {"$set": {"store_id": "STORE_123"}}
                )
            else:
                # No brand -> STORE_19CF2B
                await db.products.update_one(
                    {"_id": product['_id']},
                    {"$set": {"store_id": "STORE_19CF2B"}}
                )
        
        print(f"✅ Reverted {len(products)} products")
        
        # Verify
        dukaan_products = await db.products.find({"store_id": dukaan_store_id}).to_list(length=10)
        print(f"✅ Dukaan now has {len(dukaan_products)} products (should be 0)")
        
        store_123_products = await db.products.find({"store_id": "STORE_123"}).to_list(length=10)
        print(f"✅ STORE_123 has {await db.products.count_documents({'store_id': 'STORE_123'})} products")
        
        store_19cf2b_products = await db.products.find({"store_id": "STORE_19CF2B"}).to_list(length=10)
        print(f"✅ STORE_19CF2B has {await db.products.count_documents({'store_id': 'STORE_19CF2B'})} products")
    
    print(f"\n🎉 Products reverted successfully!")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(revert_products())
