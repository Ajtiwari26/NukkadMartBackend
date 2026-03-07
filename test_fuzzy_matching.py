#!/usr/bin/env python3
"""
Test fuzzy matching in AI scan for OCR errors
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
from app.services.inventory_service import InventoryService

load_dotenv()

async def test_fuzzy_matching():
    """Test that 'biskeri' matches 'Bisleri Water' in cross-store search"""
    
    mongodb_uri = os.getenv('MONGODB_URL')
    client = AsyncIOMotorClient(mongodb_uri)
    db = client['nukkadmart']
    
    inventory_service = InventoryService(db)
    
    # Simulate OCR result with spelling error
    ocr_items = [
        {
            "raw_text": "biskeri 2pc",
            "search_term_english": "Biskeri",  # OCR error: should be "Bisleri"
            "req_qty": 2,
            "req_unit": "piece",
            "is_unreadable": False,
            "confidence_score": 0.8
        }
    ]
    
    print("🧪 Testing fuzzy matching for OCR error: 'biskeri' -> 'bisleri'")
    print(f"   Store: DEMO_STORE_1 (Bisleri is in DEMO_STORE_2)")
    print()
    
    # Match against DEMO_STORE_1 (Bisleri is NOT in this store)
    result = await inventory_service.match_smart_cart('DEMO_STORE_1', ocr_items)
    
    print(f"\n📊 Results:")
    print(f"   Matched: {len(result.matched)}")
    print(f"   Unmatched: {len(result.unmatched)}")
    
    if result.matched:
        for match in result.matched:
            print(f"\n   ✅ Matched Product:")
            print(f"      Name: {match.name}")
            print(f"      Status: {match.status}")
            print(f"      Store: {match.source_store_name if match.is_cross_store else 'Current store'}")
            print(f"      Reason: {match.modification_reason}")
            print(f"      Confidence: {match.match_confidence}")
    
    if result.unmatched:
        for unmatch in result.unmatched:
            print(f"\n   ❌ Unmatched:")
            print(f"      Raw text: {unmatch['raw_text']}")
            print(f"      Reason: {unmatch['reason']}")
    
    client.close()
    
    # Verify success
    if result.matched and result.matched[0].name == "Bisleri Water (1L)":
        print("\n✅ TEST PASSED: Fuzzy matching successfully found 'Bisleri' from 'biskeri'")
        return True
    else:
        print("\n❌ TEST FAILED: Could not match 'biskeri' to 'Bisleri Water'")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_fuzzy_matching())
    exit(0 if success else 1)
