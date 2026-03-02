# Voice Cart Issues & Solutions

## Problems Identified:
1. "teen paneer" adds to cart immediately, then asks "add kar dun?" (already added)
2. "kar do" after sugar question updates rice quantity instead
3. Groq classifies intent before Nova Sonic responds, causing race conditions

## Root Cause:
Groq runs in parallel with Nova Sonic, so cart actions execute before AI asks for confirmation.

## Solution:
Make Groq smarter at distinguishing QUERY vs ADD:
- "teen paneer" (quantity + product) → ADD immediately (user intent is clear)
- "ek kilo sugar" (alone) → QUERY (ask first)
- "kar do" (confirmation) → Execute pending action

The key: If user mentions quantity with product name, it's an ADD command, not a query.
