#!/usr/bin/env python3
"""
Test Context-Aware Cart Logic

Tests all scenarios:
1. Item NOT in cart → QUERY → Confirm → ADD
2. Item ALREADY in cart → QUERY → User says add more → ADD
3. Item ALREADY in cart → QUERY → User says change → UPDATE
4. Item ALREADY in cart → QUERY → User says remove → REMOVE
5. Direct ADD with quantity → ADD
"""

import asyncio
from app.services.intent_classifier import IntentClassifier

async def test_all_scenarios():
    classifier = IntentClassifier()
    
    # Mock products
    products = [
        {
            'id': '1',
            'name': 'Toned Milk (500ml)',
            'brand': 'Amul',
            'price': 27,
            'weight': 'ml',
            'stock': 50
        },
        {
            'id': '2',
            'name': 'Basmati Rice (1kg)',
            'brand': 'India Gate',
            'price': 180,
            'weight': 'kg',
            'stock': 30
        }
    ]
    
    print("=" * 70)
    print("CONTEXT-AWARE CART LOGIC TEST")
    print("=" * 70)
    
    # ========== SCENARIO 1: Item NOT in cart ==========
    print("\n" + "=" * 70)
    print("SCENARIO 1: Item NOT in cart → QUERY → Confirm → ADD")
    print("=" * 70)
    
    cart = {}  # Empty cart
    
    print("\n1️⃣ User: 'milk'")
    intent = await classifier.classify_user_intent("milk", products, cart)
    print(f"   Classification: {intent['action']} (matches: {len(intent['matched_products'])})")
    
    if intent['action'] == 'query' and intent['matched_products']:
        product = intent['matched_products'][0]
        prod_id = str(product['id'])
        current_qty = cart.get(prod_id, 0)
        
        if current_qty > 0:
            print(f"   ⚠️ Item in cart: {current_qty}x")
            print(f"   AI should ask: 'Already cart mein hai. Aur add karun?'")
        else:
            print(f"   ✅ Item NOT in cart")
            print(f"   AI should ask: 'Milk ₹27 ka hai. Add kar dun?'")
    
    print("\n2️⃣ User: 'haan'")
    confirmation = await classifier.classify_confirmation("haan", {
        'action': 'add',
        'product': products[0],
        'quantity': 1.0
    })
    print(f"   Confirmation: {confirmation['decision']} (confidence: {confirmation['confidence']})")
    
    if confirmation['decision'] == 'yes':
        print(f"   ✅ Should ADD to cart: Milk x1")
    
    # ========== SCENARIO 2: Item ALREADY in cart → Add more ==========
    print("\n" + "=" * 70)
    print("SCENARIO 2: Item ALREADY in cart → QUERY → Add more")
    print("=" * 70)
    
    cart = {'1': 2}  # Milk already in cart (2x)
    
    print("\n1️⃣ User: 'milk'")
    intent = await classifier.classify_user_intent("milk", products, cart)
    print(f"   Classification: {intent['action']} (matches: {len(intent['matched_products'])})")
    
    if intent['action'] == 'query' and intent['matched_products']:
        product = intent['matched_products'][0]
        prod_id = str(product['id'])
        current_qty = cart.get(prod_id, 0)
        
        if current_qty > 0:
            print(f"   ⚠️ Item ALREADY in cart: {current_qty}x")
            print(f"   AI should ask: 'Milk already cart mein hai (2x). Aur add karun, quantity change karun, ya hata dun?'")
            print(f"   pending_action: action='query_existing', awaiting_user_intent=True")
        else:
            print(f"   ✅ Item NOT in cart")
    
    print("\n2️⃣ User: 'haan' (wants to add more)")
    existing_intent = await classifier.classify_existing_item_intent(
        "haan",
        products[0]['name'],
        2
    )
    print(f"   Existing item intent: {existing_intent['action']} (qty: {existing_intent.get('quantity')}, confidence: {existing_intent['confidence']})")
    
    if existing_intent['action'] == 'add_more':
        print(f"   ✅ Should ADD MORE: 2 + 1 = 3")
    
    # ========== SCENARIO 3: Item ALREADY in cart → Change quantity ==========
    print("\n" + "=" * 70)
    print("SCENARIO 3: Item ALREADY in cart → QUERY → Change quantity")
    print("=" * 70)
    
    cart = {'1': 2}  # Milk already in cart (2x)
    
    print("\n1️⃣ User: 'milk'")
    print(f"   (Same as Scenario 2)")
    print(f"   AI asks: 'Milk already cart mein hai (2x). Aur add karun, quantity change karun, ya hata dun?'")
    
    print("\n2️⃣ User: 'teen kar do' (change to 3)")
    existing_intent = await classifier.classify_existing_item_intent(
        "teen kar do",
        products[0]['name'],
        2
    )
    print(f"   Existing item intent: {existing_intent['action']} (qty: {existing_intent.get('quantity')}, confidence: {existing_intent['confidence']})")
    
    if existing_intent['action'] == 'update':
        print(f"   ✅ Should UPDATE: 2 → {existing_intent.get('quantity')}")
    
    # ========== SCENARIO 4: Item ALREADY in cart → Remove ==========
    print("\n" + "=" * 70)
    print("SCENARIO 4: Item ALREADY in cart → QUERY → Remove")
    print("=" * 70)
    
    cart = {'1': 2}  # Milk already in cart (2x)
    
    print("\n1️⃣ User: 'milk'")
    print(f"   (Same as Scenario 2)")
    print(f"   AI asks: 'Milk already cart mein hai (2x). Aur add karun, quantity change karun, ya hata dun?'")
    
    print("\n2️⃣ User: 'hata do' (remove)")
    existing_intent = await classifier.classify_existing_item_intent(
        "hata do",
        products[0]['name'],
        2
    )
    print(f"   Existing item intent: {existing_intent['action']} (qty: {existing_intent.get('quantity')}, confidence: {existing_intent['confidence']})")
    
    if existing_intent['action'] == 'remove':
        print(f"   ✅ Should REMOVE from cart")
    
    # ========== SCENARIO 5: Direct ADD with quantity ==========
    print("\n" + "=" * 70)
    print("SCENARIO 5: Direct ADD with quantity")
    print("=" * 70)
    
    cart = {}  # Empty cart
    
    print("\n1️⃣ User: 'ek basmati rice'")
    intent = await classifier.classify_user_intent("ek basmati rice", products, cart)
    print(f"   Classification: {intent['action']} (qty: {intent['quantity']}, matches: {len(intent['matched_products'])})")
    
    if intent['action'] == 'add':
        print(f"   ✅ Direct ADD: Basmati Rice x{intent['quantity']}")
        print(f"   AI should confirm: 'Ji sir, Basmati Rice add kar diya'")
    elif intent['action'] == 'query':
        print(f"   ⚠️ Classified as QUERY (should be ADD)")
        print(f"   But pending_action will be created with action='add'")
        print(f"   AI will ask: 'Basmati Rice ₹180 ka hai. Add kar dun?'")
    
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(test_all_scenarios())
