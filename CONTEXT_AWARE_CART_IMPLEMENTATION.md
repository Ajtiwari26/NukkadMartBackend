# Context-Aware Cart Implementation

## Problem Analysis

You identified a critical flaw in the original logic: the system didn't consider whether an item was already in the cart when processing QUERY actions. This led to ambiguous situations where the user's intent wasn't clear.

## All Possible Scenarios

### Scenario 1: Item NOT in Cart
```
User: "milk" (query)
  ↓
Nova Pro: QUERY
  ↓
Check cart: NOT in cart
  ↓
pending_action: {action: 'add', product: Milk, quantity: 1}
  ↓
AI: "Sir, Milk ₹27 ka hai. Add kar dun?"
  ↓
User: "haan"
  ↓
Confirmation: YES
  ↓
✅ Execute: ADD Milk x1
```

### Scenario 2: Item ALREADY in Cart → Add More
```
User: "milk" (query)
  ↓
Nova Pro: QUERY
  ↓
Check cart: ALREADY EXISTS (2x)
  ↓
pending_action: {action: 'query_existing', awaiting_user_intent: true, current_quantity: 2}
  ↓
AI: "Sir, Milk already cart mein hai (2x). Aur add karun, quantity change karun, ya hata dun?"
  ↓
User: "haan" or "ek aur"
  ↓
classify_existing_item_intent: ADD_MORE
  ↓
Update pending_action: {action: 'add', quantity: 1}
  ↓
AI: "Ji sir, ek aur Milk add kar diya"
  ↓
✅ Execute: ADD Milk x1 (total: 3)
```

### Scenario 3: Item ALREADY in Cart → Change Quantity
```
User: "milk" (query)
  ↓
Nova Pro: QUERY
  ↓
Check cart: ALREADY EXISTS (2x)
  ↓
pending_action: {action: 'query_existing', awaiting_user_intent: true}
  ↓
AI: "Sir, Milk already cart mein hai (2x). Aur add karun, quantity change karun, ya hata dun?"
  ↓
User: "teen kar do"
  ↓
classify_existing_item_intent: UPDATE (quantity: 3)
  ↓
Update pending_action: {action: 'update', quantity: 3}
  ↓
AI: "Ji sir, Milk ki quantity 3 kar di"
  ↓
✅ Execute: UPDATE Milk → 3
```

### Scenario 4: Item ALREADY in Cart → Remove
```
User: "milk" (query)
  ↓
Nova Pro: QUERY
  ↓
Check cart: ALREADY EXISTS (2x)
  ↓
pending_action: {action: 'query_existing', awaiting_user_intent: true}
  ↓
AI: "Sir, Milk already cart mein hai (2x). Aur add karun, quantity change karun, ya hata dun?"
  ↓
User: "hata do"
  ↓
classify_existing_item_intent: REMOVE
  ↓
Update pending_action: {action: 'remove'}
  ↓
AI: "Ji sir, Milk hata diya"
  ↓
✅ Execute: REMOVE Milk
```

### Scenario 5: Direct ADD with Quantity
```
User: "ek basmati rice"
  ↓
Nova Pro: ADD (quantity: 1) OR QUERY
  ↓
If QUERY: Create pending_action with action='add'
  ↓
AI: "Sir, Basmati Rice ₹180 ka hai. Add kar dun?"
  ↓
User: "haan"
  ↓
✅ Execute: ADD Basmati Rice x1
```

## Implementation Details

### 1. New Classifier Method: `classify_existing_item_intent()`

**File**: `NukkadBackend/app/services/intent_classifier.py`

```python
async def classify_existing_item_intent(
    self,
    user_text: str,
    product_name: str,
    current_quantity: float
) -> Dict:
    """
    When item is already in cart, classify what user wants to do:
    - add_more: Add additional quantity
    - update: Change to specific quantity
    - remove: Remove from cart
    - unclear: Need clarification
    """
```

This method uses Nova Pro to understand user intent when an item is already in the cart.

### 2. Context-Aware pending_action Creation

**File**: `NukkadBackend/app/routers/voice_assistant.py`

When Nova Pro classifies as QUERY:
1. Check if product is already in cart
2. If YES → Create `query_existing` state
3. If NO → Create `add` pending_action

```python
elif action == 'query' and matched_products:
    product = matched_products[0]
    prod_id = str(product.get('id', product.get('_id', '')))
    current_qty = session_cart.get(prod_id, 0)
    
    if current_qty > 0:
        # Item EXISTS - special state
        pending_action = {
            'action': 'query_existing',
            'product': product,
            'current_quantity': current_qty,
            'awaiting_user_intent': True
        }
        # Update context for Nova Sonic
        context_json['in_cart'] = True
        context_json['current_quantity'] = current_qty
    else:
        # Item NOT in cart - prepare for ADD
        pending_action = {
            'action': 'add',
            'product': product,
            'quantity': quantity if quantity else 1.0
        }
```

### 3. Handle User Response to query_existing

**File**: `NukkadBackend/app/routers/voice_assistant.py`

When `pending_action.action == 'query_existing'`:
1. Call `classify_existing_item_intent()`
2. Based on result, update `pending_action` to:
   - `add` (add more)
   - `update` (change quantity)
   - `remove` (remove from cart)

```python
if pending_action.get('action') == 'query_existing':
    existing_intent = await classifier.classify_existing_item_intent(
        text,
        product['name'],
        current_qty
    )
    
    if existing_intent['action'] == 'add_more':
        pending_action = {
            'action': 'add',
            'product': product,
            'quantity': quantity if quantity else 1.0
        }
    elif existing_intent['action'] == 'update':
        pending_action = {
            'action': 'update',
            'product': product,
            'quantity': quantity
        }
    elif existing_intent['action'] == 'remove':
        pending_action = {
            'action': 'remove',
            'product': product
        }
```

### 4. Updated Nova Sonic System Prompt

**File**: `NukkadBackend/app/services/nova_sonic_service.py`

Added handling for items already in cart:

```python
"1. QUERY (user asking):\n"
"   - If in_cart == true: Say 'Sir, [name] already cart mein hai ([current_quantity]x). "
"     Aur add karun, quantity change karun, ya hata dun?'\n"
"   - If options.length == 1: Tell price, ask 'Add kar dun?'\n"
```

## Benefits

1. **Clear Intent**: System knows whether user wants to add new item or modify existing
2. **Better UX**: AI asks appropriate questions based on cart state
3. **Flexible**: Handles all cart operations (add, update, remove) from queries
4. **Context-Aware**: Considers current cart state when processing user input
5. **Robust**: Works even if Nova Pro misclassifies "ek milk" as QUERY instead of ADD

## Testing

Run the comprehensive test:

```bash
cd NukkadBackend
python test_context_aware_cart.py
```

Expected output:
- ✅ Scenario 1: Item not in cart → ADD
- ✅ Scenario 2: Item in cart → Add more
- ✅ Scenario 3: Item in cart → Change quantity
- ✅ Scenario 4: Item in cart → Remove
- ✅ Scenario 5: Direct ADD with quantity

## Files Modified

1. `NukkadBackend/app/services/intent_classifier.py`
   - Added `classify_existing_item_intent()` method

2. `NukkadBackend/app/routers/voice_assistant.py`
   - Context-aware `pending_action` creation
   - Handle `query_existing` state
   - Call `classify_existing_item_intent()` when needed

3. `NukkadBackend/app/services/nova_sonic_service.py`
   - Updated system prompt to handle items already in cart

## Next Steps

1. Test with real voice: "milk" when milk is already in cart
2. Verify AI asks: "Milk already cart mein hai (2x). Aur add karun?"
3. Test responses: "haan", "teen kar do", "hata do"
4. Monitor logs for `🛒 Existing item intent` messages
5. Verify cart updates correctly for all scenarios
