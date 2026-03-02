"""
Test script to verify cart execution fix
Simulates the production error scenario
"""

# Simulate the flow:
# 1. User: "do milk packet" → Groq: ADD, 2 matches → pending_action = {action: 'add', awaiting_selection: True}
# 2. User: "full cream" → Groq: QUERY, 1 match → Should KEEP original action, update product
# 3. AI: "Full Cream Milk add kar diya" → Should execute ADD

def test_pending_action_logic():
    """Test the pending action state machine"""
    
    # Initial state
    pending_action = None
    
    # Step 1: User says "do milk packet"
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
            'quantity': 1.0,
            'awaiting_selection': True
        }
    print(f"  Pending action: {pending_action}")
    print(f"  awaiting_selection: {pending_action.get('awaiting_selection')}")
    
    # Step 2: User says "full cream"
    print("\nStep 2: User says 'full cream'")
    new_action = 'query'  # Groq classifies as QUERY
    new_matched_products = [{'name': 'Full Cream Milk', 'id': '2'}]
    
    # OLD LOGIC (BROKEN):
    # if new_action in ['add', 'update', 'remove']:
    #     pending_action = {...}  # Overwrites with QUERY action
    
    # NEW LOGIC (FIXED):
    if pending_action and pending_action.get('awaiting_selection'):
        # User is clarifying - keep original action
        selected_product = new_matched_products[0]
        pending_action = {
            'action': pending_action['action'],  # Keep 'add'
            'product': selected_product,
            'quantity': pending_action['quantity'],
            'awaiting_selection': False
        }
        print(f"  User clarified: {selected_product['name']}")
    elif new_action in ['add', 'update', 'remove']:
        # New action - create new pending
        pending_action = {
            'action': new_action,
            'product': new_matched_products[0],
            'quantity': 1.0,
            'awaiting_selection': False
        }
    
    print(f"  Pending action: {pending_action}")
    print(f"  Action type: {pending_action.get('action')}")
    print(f"  awaiting_selection: {pending_action.get('awaiting_selection')}")
    
    # Step 3: AI confirms "Full Cream Milk add kar diya"
    print("\nStep 3: AI confirms 'Full Cream Milk add kar diya'")
    ai_text = "Ji sir, Full Cream Milk add kar diya"
    confirmation_phrases = [
        'add kar diya', 'add kar di', 'daal diya', 
        'hata diya', 'remove kar diya', 'nikaal diya',
        'quantity badal di', 'update kar diya'
    ]
    is_confirmation = any(phrase in ai_text.lower() for phrase in confirmation_phrases)
    
    print(f"  Is confirmation: {is_confirmation}")
    print(f"  Awaiting selection: {pending_action.get('awaiting_selection')}")
    
    if is_confirmation and pending_action and not pending_action.get('awaiting_selection'):
        action = pending_action['action']
        product = pending_action['product']
        quantity = pending_action['quantity']
        print(f"  ✅ EXECUTING: {action.upper()} {quantity}x {product['name']}")
        pending_action = None
    else:
        print(f"  ❌ NOT EXECUTING - awaiting_selection={pending_action.get('awaiting_selection')}")
    
    print(f"\nFinal pending_action: {pending_action}")

if __name__ == '__main__':
    test_pending_action_logic()
