#!/usr/bin/env python3
"""
Test script to verify QUERY → ADD pending_action fix

This simulates the flow:
1. User: "ek basmati rice" → Nova Pro: QUERY
2. pending_action should be created with action='add'
3. AI: "Add kar dun?"
4. User: "haan" → Confirmation detected
5. AI: "add kar diya" → Cart execution triggered
"""

import asyncio
import json
from app.services.intent_classifier import IntentClassifier

async def test_query_to_add_flow():
    """Test that QUERY actions create pending_action for ADD"""
    
    classifier = IntentClassifier()
    
    # Mock products
    products = [
        {
            'id': '1',
            'name': 'Basmati Rice (1kg)',
            'brand': 'India Gate',
            'price': 180,
            'weight': 'kg',
            'stock': 50
        },
        {
            'id': '2',
            'name': 'Basmati Rice (500g)',
            'brand': 'India Gate',
            'price': 95,
            'weight': 'g',
            'stock': 30
        }
    ]
    
    cart = {}
    
    print("=" * 60)
    print("TEST: QUERY → ADD Pending Action Fix")
    print("=" * 60)
    
    # Step 1: User says "ek basmati rice"
    print("\n1️⃣ User: 'ek basmati rice'")
    user_intent = await classifier.classify_user_intent(
        "ek basmati rice",
        products,
        cart
    )
    
    print(f"   Nova Pro Classification:")
    print(f"   - Action: {user_intent['action']}")
    print(f"   - Product: {user_intent['product_name']}")
    print(f"   - Quantity: {user_intent['quantity']}")
    print(f"   - Matches: {len(user_intent['matched_products'])}")
    
    # Step 2: Check if pending_action should be created
    action = user_intent['action']
    matched_products = user_intent['matched_products']
    quantity = user_intent['quantity']
    
    pending_action = None
    
    if action == 'query' and matched_products:
        if len(matched_products) == 1:
            pending_action = {
                'action': 'add',
                'product': matched_products[0],
                'quantity': quantity if quantity else 1.0,
                'awaiting_selection': False
            }
            print(f"\n2️⃣ ✅ Created pending_action:")
            print(f"   - Action: add")
            print(f"   - Product: {matched_products[0]['name']}")
            print(f"   - Quantity: {pending_action['quantity']}")
        else:
            pending_action = {
                'action': 'add',
                'products': matched_products,
                'quantity': quantity if quantity else 1.0,
                'awaiting_selection': True
            }
            print(f"\n2️⃣ ✅ Created pending_action (multiple options):")
            print(f"   - Action: add")
            print(f"   - Products: {len(matched_products)}")
            print(f"   - Awaiting selection: True")
    else:
        print(f"\n2️⃣ ❌ No pending_action created (action={action}, matches={len(matched_products)})")
    
    # Step 3: AI asks confirmation
    ai_question = "Sir, Basmati Rice ₹180 ka hai. Add kar dun?"
    print(f"\n3️⃣ AI: '{ai_question}'")
    
    ai_class = await classifier.classify_ai_response(ai_question, pending_action)
    print(f"   Classification: {ai_class['decision']} (confidence: {ai_class['confidence']})")
    
    # Step 4: User confirms
    print(f"\n4️⃣ User: 'haan'")
    
    if pending_action:
        confirmation = await classifier.classify_confirmation("haan", pending_action)
        print(f"   Confirmation: {confirmation['decision']} (confidence: {confirmation['confidence']})")
        print(f"   Reasoning: {confirmation['reasoning']}")
    else:
        print(f"   ❌ Cannot check confirmation - no pending_action!")
    
    # Step 5: AI confirms
    ai_confirm = "Ji sir, Basmati Rice add kar diya."
    print(f"\n5️⃣ AI: '{ai_confirm}'")
    
    ai_class = await classifier.classify_ai_response(ai_confirm, pending_action)
    print(f"   Classification: {ai_class['decision']} (confidence: {ai_class['confidence']})")
    
    # Step 6: Execute cart update
    if ai_class['decision'] == 'confirmed' and ai_class['confidence'] >= 0.6 and pending_action:
        if not pending_action.get('awaiting_selection'):
            product = pending_action['product']
            quantity = pending_action['quantity']
            action = pending_action['action']
            
            print(f"\n6️⃣ ✅ CART EXECUTION:")
            print(f"   - Action: {action}")
            print(f"   - Product: {product['name']}")
            print(f"   - Quantity: {quantity}")
            print(f"   - Cart updated successfully!")
        else:
            print(f"\n6️⃣ ⏸️ Awaiting product selection")
    else:
        print(f"\n6️⃣ ❌ CART NOT UPDATED:")
        if not pending_action:
            print(f"   - Reason: No pending_action")
        elif ai_class['decision'] != 'confirmed':
            print(f"   - Reason: AI not confirmed (decision={ai_class['decision']})")
        elif ai_class['confidence'] < 0.6:
            print(f"   - Reason: Low confidence ({ai_class['confidence']})")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(test_query_to_add_flow())
