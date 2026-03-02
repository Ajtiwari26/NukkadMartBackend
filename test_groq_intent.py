"""
Test Groq Intent Classification
Verify that Groq correctly classifies user intent and generates clean instructions
"""
import asyncio
import os
from dotenv import load_dotenv
from app.services.intent_classifier import IntentClassifier

load_dotenv()

# Mock products
MOCK_PRODUCTS = [
    {'id': '1', 'name': 'Paneer Pack', 'brand': 'Amul', 'price': 85, 'stock': 10},
    {'id': '2', 'name': 'Bread', 'brand': 'Modern', 'price': 40, 'stock': 20},
    {'id': '3', 'name': 'Milk', 'brand': 'Amul', 'price': 60, 'stock': 15},
]

async def test_intent_classification():
    classifier = IntentClassifier()
    
    # Test cases
    test_cases = [
        # Query
        ("paneer chahiye", {}, "query"),
        ("bread ka price kya hai", {}, "query"),
        
        # Add
        ("do paneer ke packet", {}, "add"),
        ("teen bread chahiye", {}, "add"),
        
        # Update (item already in cart)
        ("cart mein jo do hai usko teen kar do", {'1': 2}, "update"),
        ("paneer ki quantity teen kar do", {'1': 2}, "update"),
        
        # Remove
        ("bread hataa do", {'2': 1}, "remove"),
        ("paneer nahi chahiye", {'1': 2}, "remove"),
    ]
    
    print("🧪 Testing Groq Intent Classification\n")
    
    for user_speech, cart, expected_action in test_cases:
        print(f"User: \"{user_speech}\"")
        print(f"Cart: {cart}")
        
        result = await classifier.classify_user_intent(
            user_speech, 
            MOCK_PRODUCTS,
            cart
        )
        
        if result:
            print(f"✅ Action: {result['action']}")
            print(f"   Product: {result['product']['name']}")
            print(f"   Quantity: {result['quantity']}")
            if result.get('sonic_instruction'):
                print(f"   Instruction: {result['sonic_instruction']}")
            
            if result['action'] == expected_action:
                print("   ✓ Correct action detected")
            else:
                print(f"   ✗ Expected {expected_action}, got {result['action']}")
        else:
            print("❌ No intent detected")
        
        print()

if __name__ == "__main__":
    asyncio.run(test_intent_classification())
