"""
Complete test for cart execution flow
Tests both the pending action logic and Groq classification
"""
import asyncio
import os
from dotenv import load_dotenv
from app.services.intent_classifier import IntentClassifier

load_dotenv()

async def test_groq_classification():
    """Test Groq classification for various inputs"""
    classifier = IntentClassifier()
    
    # Mock products
    products = [
        {'name': 'Toned Milk', 'brand': '', 'id': '1', 'price': 27},
        {'name': 'Full Cream Milk', 'brand': '', 'id': '2', 'price': 33},
        {'name': 'Bread', 'brand': '', 'id': '3', 'price': 40},
    ]
    
    test_cases = [
        # (user_input, expected_action, expected_quantity)
        ("milk", "query", None),  # Just asking
        ("milk chahiye", "query", None),  # Asking with chahiye
        ("do milk", "add", 2.0),  # Quantity + product = ADD
        ("do milk packet", "add", 2.0),  # Quantity + product + packet = ADD
        ("teen bread ke packet", "add", 3.0),  # Quantity + product + ke packet = ADD
        ("full cream", "query", None),  # Brand clarification
        ("Amul milk add kar do", "add", 1.0),  # Explicit add command
    ]
    
    print("Testing Groq Classification:")
    print("=" * 80)
    
    for user_input, expected_action, expected_qty in test_cases:
        result = await classifier.classify_user_intent(user_input, products, {})
        
        if result:
            actual_action = result['action']
            actual_qty = result['quantity']
            matches = len(result['matched_products'])
            
            action_match = "✅" if actual_action == expected_action else "❌"
            qty_match = "✅" if actual_qty == expected_qty else "❌"
            
            print(f"\nInput: '{user_input}'")
            print(f"  Expected: action={expected_action}, qty={expected_qty}")
            print(f"  Actual:   action={actual_action}, qty={actual_qty}, matches={matches}")
            print(f"  Result:   {action_match} action, {qty_match} quantity")
        else:
            print(f"\nInput: '{user_input}'")
            print(f"  ❌ No result from Groq")

def test_pending_action_flow():
    """Test the complete pending action state machine"""
    print("\n\n" + "=" * 80)
    print("Testing Pending Action Flow:")
    print("=" * 80)
    
    # Scenario 1: Multiple products → User clarifies → Execute
    print("\n--- Scenario 1: Multiple products with clarification ---")
    pending_action = None
    
    # Step 1: User says "do milk packet" (2 matches)
    print("Step 1: User says 'do milk packet'")
    action = 'add'
    matched_products = [
        {'name': 'Toned Milk', 'id': '1'},
        {'name': 'Full Cream Milk', 'id': '2'}
    ]
    
    if len(matched_products) > 1:
        pending_action = {
            'action': action,
            'products': matched_products,
            'quantity': 2.0,
            'awaiting_selection': True
        }
    print(f"  → Pending: action={pending_action['action']}, awaiting={pending_action['awaiting_selection']}")
    
    # Step 2: User says "full cream" (clarification)
    print("\nStep 2: User says 'full cream'")
    new_action = 'query'
    new_matched = [{'name': 'Full Cream Milk', 'id': '2'}]
    
    if pending_action and pending_action.get('awaiting_selection'):
        selected_product = new_matched[0]
        pending_action = {
            'action': pending_action['action'],  # Keep original 'add'
            'product': selected_product,
            'quantity': pending_action['quantity'],
            'awaiting_selection': False
        }
        print(f"  → Clarified: {selected_product['name']}")
    
    print(f"  → Pending: action={pending_action['action']}, awaiting={pending_action['awaiting_selection']}")
    
    # Step 3: AI confirms
    print("\nStep 3: AI says 'Full Cream Milk add kar diya'")
    ai_text = "Ji sir, Full Cream Milk add kar diya"
    confirmation_phrases = ['add kar diya', 'add kar di', 'daal diya']
    is_confirmation = any(phrase in ai_text.lower() for phrase in confirmation_phrases)
    
    if is_confirmation and pending_action and not pending_action.get('awaiting_selection'):
        print(f"  ✅ EXECUTING: {pending_action['action'].upper()} {pending_action['quantity']}x {pending_action['product']['name']}")
        pending_action = None
    else:
        print(f"  ❌ NOT EXECUTING")
    
    # Scenario 2: Single product → Execute immediately
    print("\n\n--- Scenario 2: Single product (immediate execution) ---")
    pending_action = None
    
    # Step 1: User says "teen bread ke packet" (1 match)
    print("Step 1: User says 'teen bread ke packet'")
    action = 'add'
    matched_products = [{'name': 'Bread', 'id': '3'}]
    
    if len(matched_products) == 1:
        pending_action = {
            'action': action,
            'product': matched_products[0],
            'quantity': 3.0,
            'awaiting_selection': False
        }
    print(f"  → Pending: action={pending_action['action']}, awaiting={pending_action['awaiting_selection']}")
    
    # Step 2: AI confirms
    print("\nStep 2: AI says 'teen bread ke packet add kar diya'")
    ai_text = "Ji sir, teen bread ke packet add kar diya"
    is_confirmation = any(phrase in ai_text.lower() for phrase in confirmation_phrases)
    
    if is_confirmation and pending_action and not pending_action.get('awaiting_selection'):
        print(f"  ✅ EXECUTING: {pending_action['action'].upper()} {pending_action['quantity']}x {pending_action['product']['name']}")
        pending_action = None
    else:
        print(f"  ❌ NOT EXECUTING")

if __name__ == '__main__':
    # Test Groq classification
    asyncio.run(test_groq_classification())
    
    # Test pending action flow
    test_pending_action_flow()
    
    print("\n" + "=" * 80)
    print("All tests complete!")
