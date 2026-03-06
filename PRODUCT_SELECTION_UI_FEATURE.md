# Product Selection UI Feature

## Overview

When a user asks for a product that has multiple varieties (e.g., "basmati rice" has 1kg, 500g, different brands), instead of voice confirmation, we now show a visual selection panel where the user can tap to choose which variety they want.

## User Experience Flow

```
User: "ek basmati rice" (voice)
  ↓
Backend finds 3 varieties:
  - Basmati Rice (1kg) - India Gate - ₹180
  - Basmati Rice (500g) - India Gate - ₹95
  - Regular Rice (1kg) - Local - ₹40
  ↓
Backend sends 'product_selection' event to Flutter
  ↓
Flutter shows selection panel above cart:
  ┌─────────────────────────────────────┐
  │ Select basmati rice            [X]  │
  ├─────────────────────────────────────┤
  │ [📦] Basmati Rice (1kg)        [+] │
  │      India Gate                     │
  │      ₹180 / kg                      │
  ├─────────────────────────────────────┤
  │ [📦] Basmati Rice (500g)       [+] │
  │      India Gate                     │
  │      ₹95 / g                        │
  ├─────────────────────────────────────┤
  │ [📦] Regular Rice (1kg)        [+] │
  │      Local                          │
  │      ₹40 / kg                       │
  └─────────────────────────────────────┘
  ↓
User taps on "Basmati Rice (1kg)"
  ↓
Flutter sends 'product_selected' event to backend
  ↓
Backend adds to cart
  ↓
AI confirms: "Ji sir, Basmati Rice add kar diya"
  ↓
✅ Item added to cart with animation
```

## Implementation Details

### Backend Changes

**File**: `NukkadBackend/app/routers/voice_assistant.py`

1. **Send product_selection event** when multiple products found:
```python
if len(matched_products) > 1:
    await websocket.send_text(json.dumps({
        'event': 'product_selection',
        'product_name': product_name,
        'action': action,
        'quantity': quantity,
        'options': context_json['options']
    }))
    
    pending_action = {
        'action': action,
        'products': matched_products,
        'awaiting_selection': True
    }
```

2. **Handle product_selected event** from Flutter:
```python
elif message.get('event') == 'product_selected':
    product_id = message.get('product_id')
    selected_quantity = message.get('quantity')
    
    # Find selected product from pending_action
    # Update cart
    # Send cart_update to Flutter
    # AI confirms
```

### Flutter Changes

**File**: `NukkadMart/lib/services/voice_cart_service.dart`

1. **Added ProductSelectionEvent stream**:
```dart
final _productSelectionController = StreamController<ProductSelectionEvent>.broadcast();
Stream<ProductSelectionEvent> get productSelectionStream => _productSelectionController.stream;
```

2. **Handle product_selection event**:
```dart
case 'product_selection':
  _productSelectionController.add(ProductSelectionEvent(
    productName: data['product_name'],
    action: data['action'],
    quantity: data['quantity'],
    options: data['options'].map((opt) => ProductOption.fromJson(opt)).toList(),
  ));
```

3. **Send product selection back**:
```dart
void sendProductSelection(String productId, double quantity) {
  _channel!.sink.add(json.encode({
    'event': 'product_selected',
    'product_id': productId,
    'quantity': quantity,
  }));
}
```

**File**: `NukkadMart/lib/screens/ai_voice_cart_screen.dart`

1. **Listen to product selection events**:
```dart
_voiceService.productSelectionStream.listen((selectionEvent) {
  if (mounted) {
    setState(() => _productSelection = selectionEvent);
  }
});
```

2. **Show selection panel in UI**:
```dart
if (_productSelection != null) _buildProductSelectionPanel(),
```

3. **Product selection panel** shows:
   - Header with product name and close button
   - List of product options with:
     - Product icon
     - Name and brand
     - Price and unit
     - "In cart" badge if already added
     - Add button

4. **On tap**:
   - Send selection to backend
   - Clear selection panel
   - Show drop animation (TODO)

## Benefits

1. **Visual Clarity**: User can see all options with prices before selecting
2. **Better UX**: Tap to select is faster than voice clarification
3. **Matches AI Scan**: Consistent with existing AI scan product selection
4. **Reduces Voice Errors**: No need for voice confirmation of specific variants
5. **Shows Cart State**: User can see if item is already in cart

## When Selection UI Appears

- **Multiple varieties in SAME store**: Show selection UI
- **Single product**: Direct voice confirmation (no UI)
- **Cross-store search**: Only when user explicitly asks for other shops

## Example Scenarios

### Scenario 1: Multiple Varieties
```
User: "milk"
Backend: Finds Toned Milk (₹27), Full Cream Milk (₹33)
UI: Shows selection panel
User: Taps "Toned Milk"
Result: Toned Milk added to cart
```

### Scenario 2: Single Product
```
User: "bread"
Backend: Finds only "Egg Bread (₹40)"
AI: "Sir, Bread ₹40 ka hai. Add kar dun?"
User: "haan"
Result: Bread added to cart
```

### Scenario 3: Item Already in Cart
```
User: "milk" (already has 2x Toned Milk)
Backend: Checks cart, finds existing
AI: "Sir, Milk already cart mein hai (2x). Aur add karun?"
User: "haan"
Result: Adds 1 more (total: 3)
```

## Future Enhancements

1. **Drop Animation**: Animate selected item dropping from panel to cart
2. **Quantity Selector**: Let user choose quantity in selection panel
3. **Product Images**: Show actual product images instead of icons
4. **Quick Add**: Double-tap to add without confirmation
5. **Swipe Actions**: Swipe to add/remove from selection panel

## Testing

1. Say "basmati rice" - should show 3 options
2. Tap on "Basmati Rice (1kg)" - should add to cart
3. AI should confirm: "Ji sir, Basmati Rice add kar diya"
4. Check cart - should have Basmati Rice (1kg) x1
5. Selection panel should disappear after selection

## Files Modified

1. `NukkadBackend/app/routers/voice_assistant.py` - Send product_selection event, handle product_selected
2. `NukkadMart/lib/services/voice_cart_service.dart` - Add ProductSelectionEvent stream and models
3. `NukkadMart/lib/screens/ai_voice_cart_screen.dart` - Show selection panel UI
