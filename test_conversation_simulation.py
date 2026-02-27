"""
Simulate a voice conversation with the AI shopkeeper
This simulates what would happen in a real voice conversation
"""

import asyncio
from app.services.nova_sonic_service import NovaSonicService
from app.db.mongodb import MongoDB
import os
from dotenv import load_dotenv

load_dotenv()

async def simulate_conversation():
    """Simulate a shopping conversation"""
    
    print("🏪 NukkadMart Voice Shopping Simulation")
    print("=" * 60)
    print("This simulates how the voice assistant would respond")
    print("In production, this would be actual voice conversation")
    print("=" * 60)
    print()
    
    # Connect to database
    await MongoDB.connect()
    
    # Create Nova Sonic service
    nova_sonic = NovaSonicService()
    
    # Create session
    session = await nova_sonic.create_session(
        user_id="test_customer_123",
        persona="helpful_shopkeeper",
        tools=[
            "check_inventory",
            "add_to_cart",
            "get_cart",
            "suggest_alternatives",
            "compare_brands"
        ]
    )
    
    print(f"✅ Session created: {session['id']}")
    print(f"👤 Persona: Professional Shopkeeper")
    print(f"🗣️  Language: Hindi/Hinglish")
    print()
    print("=" * 60)
    print()
    
    # Simulate conversation
    conversations = [
        {
            "customer": "Namaste",
            "ai_response": "Namaste sir, aapko kya chahiye? Main aapki help kar sakta hun",
            "action": None
        },
        {
            "customer": "Chawal chahiye",
            "ai_response": "Ji sir, main check karta hun inventory mein...",
            "action": "check_inventory",
            "tool_params": {"product_name": "chawal"}
        },
        {
            "customer": "2 kg chahiye",
            "ai_response": "Ji sir, 1kg ke 2 packet doon? Regular ya Basmati?",
            "action": None
        },
        {
            "customer": "Regular de do",
            "ai_response": "Ji sir, Regular Chawal 2kg add kar diya. Total ₹80 ho gaya. Aur kuch chahiye?",
            "action": "add_to_cart",
            "tool_params": {"product_id": "rice_regular_1kg", "quantity": 2}
        },
        {
            "customer": "Namak bhi chahiye",
            "ai_response": "Ji sir, Tata Salt ₹42 ya Local ₹28? Konsi doon?",
            "action": "check_inventory",
            "tool_params": {"product_name": "namak"}
        },
        {
            "customer": "Tata wali",
            "ai_response": "Ji sir, Tata Salt add kar diya. Total ₹122 ho gaya. Aur kuch chahiye?",
            "action": "add_to_cart",
            "tool_params": {"product_id": "tata_salt_1kg", "quantity": 1}
        },
        {
            "customer": "Bas itna hi",
            "ai_response": "Ji sir, total ₹122 ho gaya. Payment kaise karein? Cash ya UPI?",
            "action": "get_cart"
        }
    ]
    
    # Display conversation
    for i, conv in enumerate(conversations, 1):
        print(f"Turn {i}:")
        print(f"🗣️  Customer: \"{conv['customer']}\"")
        
        if conv.get('action'):
            print(f"   🔧 AI Action: {conv['action']}({conv.get('tool_params', {})})")
        
        print(f"🤖 AI Shopkeeper: \"{conv['ai_response']}\"")
        print()
        
        # Simulate processing time
        await asyncio.sleep(0.5)
    
    # Show final cart
    print("=" * 60)
    print("🛒 Final Cart:")
    print("   1. Regular Chawal 2kg - ₹80")
    print("   2. Tata Salt 1kg - ₹42")
    print("   " + "-" * 40)
    print("   Total: ₹122")
    print("=" * 60)
    print()
    
    # Show what happened behind the scenes
    print("🔍 What Happened Behind the Scenes:")
    print("   1. Customer spoke in Hindi/Hinglish")
    print("   2. Nova Sonic converted speech to text")
    print("   3. AI understood intent and called tools:")
    print("      - check_inventory('chawal')")
    print("      - add_to_cart('rice_regular_1kg', 2)")
    print("      - check_inventory('namak')")
    print("      - add_to_cart('tata_salt_1kg', 1)")
    print("      - get_cart()")
    print("   4. AI generated Hindi/Hinglish response")
    print("   5. Nova Sonic converted text to speech")
    print("   6. Customer heard AI speaking in Hindi")
    print()
    print("✅ Conversation completed successfully!")
    print()
    print("📱 In Production:")
    print("   - Customer speaks into phone microphone")
    print("   - Audio streams to backend via WebSocket")
    print("   - Nova Sonic processes in real-time")
    print("   - AI speaks back through phone speaker")
    print("   - Cart updates live on screen")
    
    # Cleanup
    await nova_sonic.close_session(session['id'])
    await MongoDB.disconnect()

if __name__ == "__main__":
    asyncio.run(simulate_conversation())
