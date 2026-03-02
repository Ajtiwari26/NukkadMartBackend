# Final Voice Cart Implementation Plan

## Issues to Fix:
1. ❌ "ek kilo sugar" → Adds immediately (should ask first)
2. ❌ "chhah kilo rice" → Adds 2x 5kg packs (wrong calculation)
3. ❌ "poora cart khaali" → Doesn't clear cart
4. ❌ "sugar aur paneer add" → Only handles one item
5. ❌ Greeting shows transcript before audio plays

## Root Causes:
- Groq prompt needs better QUERY vs ADD distinction
- Groq can't handle multiple products in one utterance
- Clear cart logic missing
- Greeting sent before Nova Sonic ready

## Solution:
1. Fix Groq prompt: "ek kilo X" alone = QUERY, "ek kilo X add kar do" = ADD
2. Add clear cart detection with keywords
3. For multiple items: Process first item only, let user add rest separately
4. Fix greeting timing: Don't send transcript for welcome message
5. Better quantity calculation for kg-based products

## Implementation:
- Update intent_classifier.py with better rules
- Add clear_cart action handling
- Fix greeting in router
- Better logging for debugging
