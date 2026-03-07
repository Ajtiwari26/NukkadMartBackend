#!/usr/bin/env python3
"""
Test script to verify demo store data exists and is accessible
"""

import asyncio
from app.db.mongodb import get_database

async def test_demo_stores():
    """Verify demo stores have products"""
    
    db = await get_database()
    
    print("=" * 70)
    print("DEMO STORE DATA VERIFICATION")
    print("=" * 70)
    
    demo_stores = ['DEMO_STORE_1', 'DEMO_STORE_2', 'DEMO_STORE_3']
    
    for store_id in demo_stores:
        print(f"\n{'='*70}")
        print(f"Store: {store_id}")
        print(f"{'='*70}")
        
        # Check if store exists
        store = await db.stores.find_one({"store_id": store_id})
        if store:
            print(f"✅ Store found: {store.get('name', 'N/A')}")
        else:
            print(f"❌ Store NOT found in database")
        
        # Check products
        products = await db.products.find({
            "store_id": store_id,
            "is_active": True
        }).to_list(length=100)
        
        print(f"\nProducts: {len(products)}")
        
        if products:
            print("\nSample products:")
            for i, p in enumerate(products[:5], 1):
                print(f"  {i}. {p.get('name')} - {p.get('brand', 'Local')} - ₹{p.get('price', 0)}")
        else:
            print("❌ NO PRODUCTS FOUND!")
            print("\nTo seed demo stores, run:")
            print(f"  python seed_demo_stores.py")
    
    print(f"\n{'='*70}")
    print("VERIFICATION COMPLETE")
    print(f"{'='*70}")

if __name__ == "__main__":
    asyncio.run(test_demo_stores())
