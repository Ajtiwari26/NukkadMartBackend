#!/usr/bin/env python3
"""
Fix demo products by adding is_available field
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

async def fix_demo_products():
    """Add is_available=True to all demo products"""
    
    # Use MONGODB_URL to match .env file
    mongodb_uri = os.getenv('MONGODB_URL', 'mongodb+srv://nukkadmart:Ajtiwari23@nukkadmart.0imveqj.mongodb.net/?appName=NukkadMart')
    print(f"Connecting to MongoDB...")
    client = AsyncIOMotorClient(mongodb_uri)
    db = client['nukkadmart']
    
    print("🔧 Fixing demo products...")
    
    # Update all demo products to have is_available=True
    result = await db.products.update_many(
        {"is_demo": True},
        {"$set": {"is_available": True}}
    )
    
    print(f"✅ Updated {result.modified_count} demo products")
    
    # Verify
    demo_products = await db.products.count_documents({
        "is_demo": True,
        "is_active": True,
        "is_available": True
    })
    
    print(f"✅ Verified: {demo_products} demo products now have is_active=True and is_available=True")
    
    # Show sample
    sample = await db.products.find_one({"is_demo": True})
    if sample:
        print(f"\nSample product:")
        print(f"  Name: {sample.get('name')}")
        print(f"  Store: {sample.get('store_id')}")
        print(f"  is_active: {sample.get('is_active')}")
        print(f"  is_available: {sample.get('is_available')}")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(fix_demo_products())
