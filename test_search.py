"""Quick test for hybrid search quality"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from motor.motor_asyncio import AsyncIOMotorClient
from app.services.search_service import get_search_service

async def test():
    client = AsyncIOMotorClient(os.getenv('MONGODB_URL'))
    db = client[os.getenv('MONGODB_DATABASE', 'nukkadmart')]
    
    # Load DEMO_STORE_1 products
    products = await db.products.find({"store_id": "DEMO_STORE_1", "is_active": True}).to_list(100)
    print(f"Loaded {len(products)} products from DEMO_STORE_1")
    
    search = get_search_service()
    
    test_queries = [
        "Rice",
        "mirchi powder",
        "dahi",
        "bisleri",
        "Ashirvaad",
        "sugar",
        "paneer",
    ]
    
    for q in test_queries:
        results = search.search(q, products, limit=3, min_score=0.10)
        print(f"\n🔍 '{q}' →")
        if results:
            for score, p in results:
                print(f"   {score:.3f} | {p['name']} ({p.get('brand', '-')})")
        else:
            print("   ❌ No matches")
    
    # Also test cross-store: bisleri in DEMO_STORE_2
    products_2 = await db.products.find({"store_id": "DEMO_STORE_2", "is_active": True}).to_list(100)
    print(f"\n--- DEMO_STORE_2 ({len(products_2)} products) ---")
    results_2 = search.search("bisleri", products_2, limit=3, min_score=0.10)
    print(f"🔍 'bisleri' in STORE_2 →")
    if results_2:
        for score, p in results_2:
            print(f"   {score:.3f} | {p['name']} ({p.get('brand', '-')})")
    else:
        print("   ❌ No matches")
    
    client.close()

asyncio.run(test())
