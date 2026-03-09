"""
Voice Assistant Router - SYNCHRONOUS VERSION (No Race Conditions)
Groq classifies intent → Inject to Nova Sonic → Nova Sonic responds
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.services.nova_sonic_service import NovaSonicService
from app.services.voice_context_service import VoiceContextService
from app.services.intent_classifier import IntentClassifier
from app.db.redis import RedisClient
import json
import asyncio
import logging
import httpx
import base64
import os
import re
from enum import Enum

router = APIRouter()
logger = logging.getLogger(__name__)


def transliterate_hindi_to_english(text: str) -> str:
    """
    Transliterate Hindi Devanagari text to English (Roman script).
    Converts: कॉफी → coffee, कर दो → kar do
    """
    # Devanagari to Roman mapping
    devanagari_map = {
        # Vowels
        'अ': 'a', 'आ': 'aa', 'इ': 'i', 'ई': 'ee', 'उ': 'u', 'ऊ': 'oo',
        'ऋ': 'ri', 'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au',
        # Consonants
        'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ng',
        'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'ny',
        'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n',
        'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
        'प': 'p', 'फ': 'ph', 'ब': 'b', 'भ': 'bh', 'म': 'm',
        'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'v', 'श': 'sh',
        'ष': 'sh', 'स': 's', 'ह': 'h',
        # Vowel signs (matras)
        'ा': 'aa', 'ि': 'i', 'ी': 'ee', 'ु': 'u', 'ू': 'oo',
        'ृ': 'ri', 'े': 'e', 'ै': 'ai', 'ो': 'o', 'ौ': 'au',
        'ं': 'm', 'ः': 'h', '्': '', 'ँ': 'n',
        # Special characters
        'ॉ': 'o', 'ऑ': 'o',
    }
    
    result = []
    for char in text:
        if char in devanagari_map:
            result.append(devanagari_map[char])
        else:
            result.append(char)
    
    return ''.join(result)


def _clean_text_for_tts(text: str) -> str:
    """Clean text for natural TTS — remove punctuation that sounds bad when read aloud."""
    # Replace ₹ symbol with "rupees" so it's spoken naturally
    text = text.replace('₹', ' rupees ')
    # Remove parentheses and brackets but keep the content inside
    text = re.sub(r'[()\[\]{}]', ' ', text)
    # Remove commas, full stops, colons, semicolons, exclamation, dashes, asterisks, quotes
    text = re.sub(r'[,\.;:!\-–—*\"\'\?_]', ' ', text)
    # Collapse multiple spaces into one
    text = re.sub(r'\s+', ' ', text).strip()
    return text


async def generate_sarvam_tts(text: str) -> bytes | None:
    """Generate high-quality Hindi TTS using Sarvam AI API"""
    url = "https://api.sarvam.ai/text-to-speech"
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        return None

    # Clean text for natural speech
    clean_text = _clean_text_for_tts(text)

    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": [clean_text],
        "target_language_code": "hi-IN",
        "speaker": "shubh",
        "pace": 1.05,
        "speech_sample_rate": 24000,
        "enable_preprocessing": True,
        "model": "bulbul:v3"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=headers, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                if data.get('audios') and len(data['audios']) > 0:
                    return base64.b64decode(data['audios'][0])
        except Exception as e:
            logger.error(f"Sarvam TTS error: {e}")
    return None


# Hindi number words for quantity detection
HINDI_NUMBERS = {
    'ek': 1, 'do': 2, 'teen': 3, 'char': 4, 'paanch': 5,
    'chhah': 6, 'saat': 7, 'aath': 8, 'nau': 9, 'das': 10,
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5
}

# Cancel keywords — recognized in all non-IDLE states
CANCEL_KEYWORDS = {'cancel', 'chhod do', 'chhodo', 'rehne do', 'nahi chahiye',
                   'mat karo', 'band karo', 'kuch nahi', 'jaane do', 'ruko',
                   'rehne de', 'chhod de', 'mat kar'}


def _get_prod_id(product: dict) -> str:
    """Normalize product ID extraction — single source of truth."""
    return str(product.get('id', product.get('_id', '')))


async def _execute_cart_action(
    action: str, product: dict, quantity: float,
    websocket: WebSocket, session_cart: dict
) -> None:
    """Execute a cart action and send the update to Flutter.
    Shared by both voice-confirmation and UI-selection paths."""
    prod_id = _get_prod_id(product)
    store_id = product.get('store_id', '')

    # Update server-side session cart
    if action == 'add':
        session_cart[prod_id] = session_cart.get(prod_id, 0) + quantity
    elif action == 'update':
        session_cart[prod_id] = quantity
    elif action == 'remove':
        session_cart.pop(prod_id, None)

    # Send cart_update event to Flutter
    await websocket.send_text(json.dumps({
        'event': 'cart_update',
        'action': action,
        'store_id': store_id,
        'quantity': quantity,
        'product': {
            'product_id': prod_id,
            'store_id': store_id,
            'name': product['name'],
            'category': product.get('category', 'General'),
            'brand': product.get('brand'),
            'price': product.get('price', 0),
            'unit': product.get('weight', product.get('unit')),
            'stock_quantity': product.get('stock', 0),
            'image_url': product.get('image_url'),
            'tags': product.get('tags', []),
        }
    }))

    logger.info(f"✅ Executed: {action.upper()} {quantity}x {product['name']}")

class ConversationState(Enum):
    IDLE = "IDLE"                                     # Waiting for user input
    AWAITING_STORE_APPROVAL = "AWAITING_STORE_APPROVAL" # Asked permission for cross-store
    AWAITING_CONFIRM = "AWAITING_CONFIRM"             # Asking to confirm single item
    AWAITING_SELECTION = "AWAITING_SELECTION"         # Showing UI for multiple varieties
    AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION" # Asking user to clarify modify vs add more

async def _resolve_products(product_name, brand, context_products, approved_stores, current_store_id, intent_classifier):
    """
    Unified product resolution pipeline for all voice actions.
    Searches current store -> approved stores -> other stores.
    Returns: (matched_products, source_store_id, needs_approval)
    """
    # 1. Search current context (Current Store + Approved Stores already merged)
    matched_products = intent_classifier._find_matching_products(
        product_name, brand, context_products
    )
    
    if matched_products:
        return matched_products, current_store_id, False
        
    # 2. If no matches and in demo mode, search OTHER demo stores
    if not matched_products and current_store_id and current_store_id.startswith('DEMO_STORE_'):
        logger.info(f"🔍 Item not found in context, searching other demo stores...")
        other_stores = ['DEMO_STORE_1', 'DEMO_STORE_2', 'DEMO_STORE_3']
        other_stores.remove(current_store_id)
        
        from app.db.mongodb import get_database
        db = await get_database()
        
        for other_store_id in other_stores:
            other_products = await db.products.find({'store_id': other_store_id}).to_list(length=100)
            other_matches = intent_classifier._find_matching_products(
                product_name, brand, other_products
            )
            
            if other_matches:
                needs_approval = other_store_id not in approved_stores
                if needs_approval:
                    logger.info(f"✅ Found {len(other_matches)} matches in {other_store_id} (needs approval)")
                else:
                    logger.info(f"✅ Found {len(other_matches)} matches in APPROVED store {other_store_id}")
                return other_matches, other_store_id, needs_approval
                
    return [], current_store_id, False


@router.websocket("/ws/voice/customer/{user_id}")
async def customer_voice_assistant(
    websocket: WebSocket,
    user_id: str,
    latitude: float = Query(None),
    longitude: float = Query(None),
    store_id: str = Query(None)
):
    """
    SYNCHRONOUS voice assistant - NO RACE CONDITIONS
    Flow: User speaks → Groq classifies → Inject to Sonic → Sonic responds
    
    For demo mode: Only store_id is required (latitude/longitude optional)
    For normal mode: latitude/longitude required for nearby store search
    """
    await websocket.accept()
    
    # Demo mode: store_id provided, no location needed
    if store_id and (latitude is None or longitude is None):
        logger.info(f"Customer voice session started for user: {user_id}, store_id={store_id} (DEMO MODE)")
        latitude = 0.0  # Dummy coordinates for demo
        longitude = 0.0
    else:
        logger.info(f"Customer voice session started for user: {user_id} at ({latitude}, {longitude}), store_id={store_id}")
    
    nova_sonic = NovaSonicService()
    context_service = VoiceContextService()
    intent_classifier = IntentClassifier()
    
    # Initialize session
    session = await nova_sonic.create_session(
        user_id=user_id,
        persona="helpful_shopkeeper",
        tools=[]
    )
    
    session_id = session['id']
    context_products = []
    session_cart = {}
    current_store_id = store_id  # Capture for use in nested functions
    
    # State machine and explicitly typed pending action sharing
    shared_state = {
        'state': ConversationState.IDLE,
        'pending': None,           # Shape: {action, products, quantity, source_store_id, ...}
        'approved_stores': set(),  # Stores user has approved for cross-store adds
        'processing': False,       # Lock: True while state machine is processing (suppress AI)
        'last_product_name': None, # Last discussed product name for pronoun resolution ('isko')
    }
    
    # Load context
    try:
        if store_id:
            # Load inventory for specific store
            logger.info(f"Loading inventory for specific store: {store_id}")
            db = await context_service._get_db()
            
            # Get store info
            store_doc = await db.stores.find_one({"store_id": store_id})
            store_name = store_doc.get('name', store_id) if store_doc else store_id
            
            # Get products for this store
            products = await context_service._load_store_inventory(store_id)
            
            # Tag each product with store info
            for p in products:
                p['store_id'] = store_id
                p['store_name'] = store_name
            
            # Store in Redis
            context_data = {
                'stores': [{'store_id': store_id, 'name': store_name}],
                'available_products': products,
                'user_id': user_id,
                'session_id': session_id
            }
            redis = RedisClient()
            await redis.setex(f"voice_context:{session_id}", 3600, json.dumps(context_data, default=str))
            
            context_summary = {
                'stores_count': 1,
                'products_count': len(products),
                'selected_store': store_name
            }
            context_products = products
        else:
            context_summary = await context_service.initialize_customer_context(
                session_id=session_id,
                user_id=user_id,
                latitude=latitude,
                longitude=longitude,
                radius_km=10.0
            )
        
        await websocket.send_text(json.dumps({
            'event': 'context_loaded',
            'data': context_summary
        }))
        
        logger.info(f"Context loaded: {context_summary.get('stores_count', 0)} stores, {context_summary.get('products_count', 0)} products")
    except Exception as e:
        logger.error(f"Error loading context: {e}")
    
    # Send context to Nova Sonic
    try:
        context = await context_service.get_context(session_id)
        if context:
            await nova_sonic.send_context(session_id, context)
            context_products = context.get('available_products', [])
            logger.info(f"Context sent to Nova Sonic ({len(context_products)} products)")
    except Exception as e:
        logger.error(f"Error sending context: {e}")
    
    # Send welcome TTS
    try:
        welcome_pcm = await generate_sarvam_tts("Namaste! Bataiye aapko kya chahiye?")
        if welcome_pcm:
            await websocket.send_bytes(welcome_pcm)
    except Exception as e:
        logger.error(f"Error sending welcome TTS: {e}")
    
    # Response processing
    response_queue = asyncio.Queue()
    
    async def process_responses():
        try:
            async for response in nova_sonic.receive_responses(session_id):
                await response_queue.put(response)
        except Exception as e:
            logger.error(f"Response processing error: {e}")
            await response_queue.put(None)
    
    response_task = asyncio.create_task(process_responses())
    
    async def forward_responses():
        """SYNCHRONOUS: Wait for Groq before forwarding AI response"""
        try:
            while True:
                response = await response_queue.get()
                if response is None:
                    break
                
                if response['type'] == 'audio_output':
                    pass  # Drop Nova Sonic audio
                    
                elif response['type'] == 'transcript':
                    is_user = response.get('is_user', False)
                    text = response['text']
                    
                    if is_user:
                        # Transliterate Hindi Devanagari to English for product search
                        text_transliterated = transliterate_hindi_to_english(text)
                        
                        # Forward transliterated transcript to user
                        await websocket.send_text(json.dumps({
                            'event': 'transcript',
                            'text': text_transliterated,
                            'is_user': True
                        }))
                        
                        if not context_products:
                            continue
                        
                        # Send processing indicator so user sees visual feedback
                        await websocket.send_text(json.dumps({'event': 'processing'}))
                        shared_state['processing'] = True  # Suppress AI responses during processing
                        
                        # Use transliterated text for intent classification
                        text = text_transliterated
                            
                        # === STATE MACHINE: DECIDE NEXT STATE ===
                        current_state = shared_state['state']
                        
                        if current_state == ConversationState.IDLE:
                            # === PRE-CLASSIFIER: Bulk store operations ===
                            text_lower = text.strip().lower()
                            bulk_store_match = None
                            
                            # Detect "remove/hata/clear all from store X" patterns
                            store_name_map = {}
                            for p in context_products:
                                sid = p.get('store_id', '')
                                sname = p.get('store_name', sid)
                                store_name_map[sid] = sname
                            
                            # Match patterns: "store 2", "shop 2", "testshop 2", "dusri shop", "teesri shop"
                            bulk_remove_patterns = [
                                r'(?:remove|hata|nikaal|clear|empty|saaf)\s.*(?:store|shop|dukaan)\s*(\d+)',
                                r'(?:store|shop|dukaan)\s*(\d+)\s.*(?:remove|hata|nikaal|clear|empty|saaf|sab.*hata)',
                                r'(?:remove|hata|nikaal|clear)\s.*(?:all|sab|saare|sara).*(?:store|shop)\s*(\d+)',
                                r'(?:store|shop)\s*(\d+)\s*(?:ke|ka|ki)?\s*(?:sab|all|saare|sara)\s.*(?:remove|hata|nikaal)',
                            ]
                            
                            for pattern in bulk_remove_patterns:
                                m = re.search(pattern, text_lower)
                                if m:
                                    store_num = m.group(1)
                                    # Map store number to store_id
                                    for sid in store_name_map:
                                        if store_num in sid:  # e.g., "2" in "DEMO_STORE_2"
                                            bulk_store_match = sid
                                            break
                                    break
                            
                            if bulk_store_match:
                                # Find all cart items from this store
                                store_items = []
                                for p in context_products:
                                    pid = _get_prod_id(p)
                                    if p.get('store_id') == bulk_store_match and pid in session_cart and session_cart[pid] > 0:
                                        store_items.append(p)
                                
                                if not store_items:
                                    store_display = store_name_map.get(bulk_store_match, bulk_store_match)
                                    msg = f"Sir, {store_display} se cart mein koi item nahi hai"
                                    pcm = await generate_sarvam_tts(msg)
                                    await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                    if pcm: await websocket.send_bytes(pcm)
                                else:
                                    # Remove all items from this store
                                    removed_names = []
                                    for p in store_items:
                                        await _execute_cart_action('remove', p, 0, websocket, session_cart)
                                        removed_names.append(p['name'])
                                    
                                    store_display = store_name_map.get(bulk_store_match, bulk_store_match)
                                    msg = f"Ji sir, {store_display} ke {len(store_items)} items cart se hata diye: {', '.join(removed_names)}"
                                    pcm = await generate_sarvam_tts(msg)
                                    await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                    if pcm: await websocket.send_bytes(pcm)
                                    logger.info(f"🗑️ Bulk removed {len(store_items)} items from store {bulk_store_match}")
                                
                                shared_state['processing'] = False
                                continue
                            
                            # 1. Classify New Intent
                            user_intent = await intent_classifier.classify_user_intent(
                                text, context_products, session_cart, shared_state.get('last_product_name')
                            )
                            
                            if not user_intent:
                                # Unrecognized speech — send a helpful fallback
                                msg = "Sir, kya chahiye? Product ka naam boliye"
                                pcm = await generate_sarvam_tts(msg)
                                await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                if pcm: await websocket.send_bytes(pcm)
                                shared_state['processing'] = False
                                continue
                                
                            action = user_intent['action']
                            product_name = user_intent['product_name']
                            brand = user_intent['brand']
                            quantity = user_intent['quantity'] or 1.0
                            is_relative = user_intent.get('is_relative', False)
                            
                            # === SMART OVERRIDES (before product resolution) ===
                            if action == 'update' and len(session_cart) == 0:
                                # UPDATE on empty cart → override to ADD
                                action = 'add'
                                msg = f"Sir, cart khali hai. {product_name} add kar deta hoon"
                                pcm = await generate_sarvam_tts(msg)
                                await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                if pcm: await websocket.send_bytes(pcm)
                                logger.info(f"⚡ Smart override: UPDATE on empty cart → ADD")
                            elif action == 'remove' and len(session_cart) == 0:
                                # REMOVE on empty cart → inform and skip
                                msg = f"Sir, cart khali hai, kuch nahi hai remove karne ko"
                                pcm = await generate_sarvam_tts(msg)
                                await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                if pcm: await websocket.send_bytes(pcm)
                                logger.info(f"⚡ Smart override: REMOVE on empty cart → inform")
                                shared_state['processing'] = False
                                continue
                            
                            # 2. Resolve Products (Unified pipeline)
                            matches, source_store, needs_approval = await _resolve_products(
                                product_name, brand, context_products, 
                                shared_state['approved_stores'], current_store_id, 
                                intent_classifier
                            )
                            
                            if len(matches) == 0:
                                # Not found anywhere → IDLE
                                msg = f"Sir, {product_name} available nahi hai"
                                pcm = await generate_sarvam_tts(msg)
                                await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                if pcm: await websocket.send_bytes(pcm)
                                logger.info(f"🚫 No matches for '{product_name}'")
                                
                            elif needs_approval:
                                # Found cross-store -> AWAITING_STORE_APPROVAL
                                store_names = {
                                    'DEMO_STORE_1': 'TestShop 1',
                                    'DEMO_STORE_2': 'TestShop 2',
                                    'DEMO_STORE_3': 'TestShop 3'
                                }
                                store_name = store_names.get(source_store, 'other shop')
                                
                                shared_state['state'] = ConversationState.AWAITING_STORE_APPROVAL
                                shared_state['pending'] = {
                                    'action': action,
                                    'products': matches,
                                    'quantity': quantity,
                                    'source_store_id': source_store,
                                    'product_name': product_name
                                }
                                
                                # Send cross-store question directly via manual TTS
                                # (Don't rely on Nova Sonic — its responses are suppressed in this state)
                                cross_msg = f"Sir, {product_name} yahan nahi hai, lekin {store_name} mein available hai. Wahan se add kar dun?"
                                pcm = await generate_sarvam_tts(cross_msg)
                                await websocket.send_text(json.dumps({'event': 'transcript', 'text': cross_msg, 'is_user': False}))
                                if pcm: await websocket.send_bytes(pcm)
                                logger.info(f"🏪 Cross-store confirmation required for {source_store}")
                                
                            elif len(matches) == 1:
                                product = matches[0]
                                prod_id = _get_prod_id(product)
                                current_qty = session_cart.get(prod_id, 0)
                                
                                # Smart overrides for single match
                                if action in ('update', 'remove') and current_qty == 0:
                                    if action == 'update':
                                        # UPDATE on item not in cart → override to ADD
                                        action = 'add'
                                        logger.info(f"⚡ Smart override: UPDATE on {product['name']} not in cart → ADD")
                                    else:
                                        # REMOVE on item not in cart → inform
                                        msg = f"Sir, {product['name']} cart mein nahi hai, hata nahi sakta"
                                        pcm = await generate_sarvam_tts(msg)
                                        await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                        if pcm: await websocket.send_bytes(pcm)
                                        logger.info(f"⚡ Smart override: REMOVE on {product['name']} not in cart → inform")
                                        shared_state['processing'] = False
                                        continue
                                
                                # Handle relative quantity for UPDATE
                                if action == 'update' and is_relative and current_qty > 0:
                                    new_qty = current_qty + quantity
                                    if new_qty <= 0:
                                        # Relative math dropped to 0 → route to REMOVE
                                        action = 'remove'
                                        quantity = 0
                                        logger.info(f"⚡ Relative qty update → qty={new_qty} ≤ 0. Auto-routing to REMOVE")
                                    else:
                                        quantity = new_qty
                                        logger.info(f"📐 Relative qty: {current_qty} + {user_intent['quantity']} = {new_qty}")
                                
                                if action == 'query' and current_qty > 0:
                                    # Item explicitly queried but already in cart → AWAITING_CLARIFICATION
                                    shared_state['state'] = ConversationState.AWAITING_CLARIFICATION
                                    shared_state['pending'] = {
                                        'action': 'query_existing',
                                        'product': product,
                                        'current_quantity': current_qty
                                    }
                                    
                                    # Manual TTS clarification prompt (don't rely on Nova Sonic)
                                    clar_msg = f"Sir, {product['name']} already cart mein hai, {int(current_qty)} quantity. Aur add karun, quantity change karun, ya hata dun?"
                                    pcm = await generate_sarvam_tts(clar_msg)
                                    await websocket.send_text(json.dumps({'event': 'transcript', 'text': clar_msg, 'is_user': False}))
                                    if pcm: await websocket.send_bytes(pcm)
                                    logger.info(f"📋 QUERY existing item: {product['name']} (qty: {current_qty})")
                                else:
                                    # Single match → AWAITING_CONFIRM (Voice confirmation)
                                    final_action = 'add' if action == 'query' else action
                                    shared_state['state'] = ConversationState.AWAITING_CONFIRM
                                    shared_state['pending'] = {
                                        'action': final_action,
                                        'product': product,
                                        'quantity': quantity
                                    }
                                    
                                    # Manual TTS confirmation (don't rely on Nova Sonic — it may have stale context)
                                    if final_action == 'add':
                                        conf_msg = f"Sir, {product['name']} add karun? {int(quantity) if quantity == int(quantity) else quantity} quantity?"
                                    elif final_action == 'update':
                                        conf_msg = f"Sir, {product['name']} ki quantity {int(quantity) if quantity == int(quantity) else quantity} kar dun?"
                                    elif final_action == 'remove':
                                        conf_msg = f"Sir, {product['name']} cart se hata dun?"
                                    else:
                                        conf_msg = f"Sir, {product['name']} {final_action} karun?"
                                    
                                    pcm = await generate_sarvam_tts(conf_msg)
                                    await websocket.send_text(json.dumps({'event': 'transcript', 'text': conf_msg, 'is_user': False}))
                                    if pcm: await websocket.send_bytes(pcm)
                                    logger.info(f"🧠 AWAITING_CONFIRM for {product['name']} ({final_action})")
                                    shared_state['last_product_name'] = product['name']
                                    
                            else:
                                # Multiple matches
                                final_action = 'add' if action == 'query' else action
                                
                                # Smart in-cart filtering for all actions
                                in_cart_matches = [
                                    p for p in matches
                                    if session_cart.get(_get_prod_id(p), 0) > 0
                                ]
                                
                                # Debug logging
                                for p in matches:
                                    pid = _get_prod_id(p)
                                    logger.info(f"🔍 Match: {p['name']} → pid='{pid}', in_cart={session_cart.get(pid, 0)}")
                                logger.info(f"🔍 session_cart keys: {list(session_cart.keys())}")
                                
                                # QUERY with exactly 1 item in cart → AWAITING_CLARIFICATION
                                if action == 'query' and len(in_cart_matches) == 1:
                                    product = in_cart_matches[0]
                                    prod_id = _get_prod_id(product)
                                    current_qty = session_cart.get(prod_id, 0)
                                    shared_state['state'] = ConversationState.AWAITING_CLARIFICATION
                                    shared_state['pending'] = {
                                        'action': 'query_existing',
                                        'product': product,
                                        'current_quantity': current_qty
                                    }
                                    
                                    # Manual TTS clarification prompt
                                    clar_msg = f"Sir, {product['name']} already cart mein hai, {int(current_qty)} quantity. Aur add karun, quantity change karun, ya hata dun?"
                                    pcm = await generate_sarvam_tts(clar_msg)
                                    await websocket.send_text(json.dumps({'event': 'transcript', 'text': clar_msg, 'is_user': False}))
                                    if pcm: await websocket.send_bytes(pcm)
                                    logger.info(f"📋 QUERY existing in-cart item: {product['name']} (qty: {current_qty})")
                                    shared_state['processing'] = False
                                    continue
                                
                                # UPDATE/REMOVE with exactly 1 item in cart → AWAITING_CONFIRM
                                if final_action in ('update', 'remove') and len(in_cart_matches) == 1:
                                    product = in_cart_matches[0]
                                    shared_state['state'] = ConversationState.AWAITING_CONFIRM
                                    shared_state['pending'] = {
                                        'action': final_action,
                                        'product': product,
                                        'quantity': quantity
                                    }
                                    
                                    # Manual TTS confirmation
                                    if final_action == 'update':
                                        conf_msg = f"Sir, {product['name']} ki quantity {int(quantity) if quantity == int(quantity) else quantity} kar dun?"
                                    else:
                                        conf_msg = f"Sir, {product['name']} cart se hata dun?"
                                    
                                    pcm = await generate_sarvam_tts(conf_msg)
                                    await websocket.send_text(json.dumps({'event': 'transcript', 'text': conf_msg, 'is_user': False}))
                                    if pcm: await websocket.send_bytes(pcm)
                                    logger.info(f"🧠 AWAITING_CONFIRM for {product['name']} (only in-cart match, {final_action})")
                                    shared_state['last_product_name'] = product['name']
                                    shared_state['processing'] = False
                                    continue
                                
                                # Narrow to in-cart matches if multiple
                                if final_action in ('update', 'remove') and len(in_cart_matches) > 1:
                                    matches = in_cart_matches
                                
                                # Show selection UI
                                shared_state['state'] = ConversationState.AWAITING_SELECTION
                                shared_state['pending'] = {
                                    'action': final_action,
                                    'products': matches,
                                    'quantity': quantity,
                                    'source_store_id': source_store
                                }
                                
                                options = []
                                for prod in matches[:5]:
                                    prod_id = _get_prod_id(prod)
                                    options.append({
                                        "product_id": prod_id, "name": prod.get('name'), "brand": prod.get('brand'),
                                        "price": prod.get('price', 0), "unit": prod.get('weight', prod.get('unit')),
                                        "in_cart": int(session_cart.get(prod_id, 0)), "store_id": prod.get('store_id')
                                    })
                                
                                await websocket.send_text(json.dumps({
                                    'event': 'product_selection',
                                    'product_name': product_name,
                                    'action': final_action,
                                    'quantity': quantity,
                                    'options': options
                                }))
                                
                                # Send manual TTS (don't rely on Nova Sonic — its response is suppressed in AWAITING_SELECTION)
                                sel_msg = f"Sir, {len(matches)} varieties available hain. Screen pe dekh lijiye"
                                pcm = await generate_sarvam_tts(sel_msg)
                                await websocket.send_text(json.dumps({'event': 'transcript', 'text': sel_msg, 'is_user': False}))
                                if pcm: await websocket.send_bytes(pcm)
                                logger.info(f"📋 AWAITING_SELECTION: {len(matches)} options")

                        elif current_state == ConversationState.AWAITING_STORE_APPROVAL:
                            # Handle cross-store YES/NO/CANCEL
                            pending = shared_state['pending']
                            text_lower_check = text.strip().lower()
                            
                            if text_lower_check in CANCEL_KEYWORDS:
                                shared_state['state'] = ConversationState.IDLE
                                shared_state['pending'] = None
                                msg = "Theek hai"
                                pcm = await generate_sarvam_tts(msg)
                                await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                if pcm: await websocket.send_bytes(pcm)
                                logger.info("🛑 CANCEL in AWAITING_STORE_APPROVAL")
                            else:
                                confirmation = await intent_classifier.classify_confirmation(text)
                            
                                if confirmation['decision'] == 'yes' and confirmation['confidence'] >= 0.6:
                                    # Store approved! Transition to 1 match or N matches logic
                                    source_store = pending['source_store_id']
                                    shared_state['approved_stores'].add(source_store)
                                    matches = pending['products']
                                    
                                    # Auto-merge into context
                                    for p in matches:
                                        if p not in context_products:
                                            context_products.append(p)
                                    logger.info(f"🏪 Approved store {source_store}, merged products into context")
                                    
                                    if len(matches) == 1:
                                        # Execute immediately
                                        product = matches[0]
                                        await _execute_cart_action(
                                            pending['action'], product, pending['quantity'],
                                            websocket, session_cart
                                        )
                                        shared_state['state'] = ConversationState.IDLE
                                        shared_state['pending'] = None
                                        
                                        # Build dynamic confirmation text with quantity
                                        qty_int = int(pending['quantity']) if pending['quantity'] == int(pending['quantity']) else pending['quantity']
                                        conf_text = f"Ji sir, {product['name']} {qty_int} quantity add kar diya"
                                        pcm = await generate_sarvam_tts(conf_text)
                                        await websocket.send_text(json.dumps({'event': 'transcript', 'text': conf_text, 'is_user': False}))
                                        if pcm: await websocket.send_bytes(pcm)
                                    else:
                                        # Show selection UI
                                        shared_state['state'] = ConversationState.AWAITING_SELECTION
                                        options = []
                                        for prod in matches[:5]:
                                            prod_id = _get_prod_id(prod)
                                            options.append({
                                                "product_id": prod_id, "name": prod.get('name'), "brand": prod.get('brand'),
                                                "price": prod.get('price', 0), "unit": prod.get('weight', prod.get('unit')),
                                                "in_cart": int(session_cart.get(prod_id, 0)), "store_id": prod.get('store_id')
                                            })
                                        await websocket.send_text(json.dumps({
                                            'event': 'product_selection', 'product_name': pending['product_name'],
                                            'action': pending['action'], 'quantity': pending['quantity'], 'options': options
                                        }))
                                        
                                        msg = f"Sir, {len(matches)} varieties available hain. Screen pe dekh lijiye"
                                        pcm = await generate_sarvam_tts(msg)
                                        await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                        if pcm: await websocket.send_bytes(pcm)
                                        
                                elif confirmation['decision'] == 'no' and confirmation['confidence'] >= 0.6:
                                    shared_state['state'] = ConversationState.IDLE
                                    shared_state['pending'] = None
                                    msg = "Theek hai, nahi add karte"
                                    pcm = await generate_sarvam_tts(msg)
                                    await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                    if pcm: await websocket.send_bytes(pcm)
                                    logger.info("❌ Cross-store denied")
                                else:
                                    # Unclear — user likely said something new
                                    logger.info(f"❓ Unclear cross-store confirmation: '{text}' — resetting to IDLE")
                                    shared_state['state'] = ConversationState.IDLE
                                    shared_state['pending'] = None
                        
                        elif current_state == ConversationState.AWAITING_CONFIRM:
                            # Handle single item YES/NO/CANCEL (with optional quantity override)
                            text_stripped = text.strip().lower()
                            
                            # Check cancel keywords first — set confirmation to cancel
                            if text_stripped in CANCEL_KEYWORDS:
                                confirmation = {'decision': 'cancel', 'confidence': 1.0}
                            elif text_stripped in HINDI_NUMBERS:
                                qty = HINDI_NUMBERS[text_stripped]
                                shared_state['pending']['quantity'] = float(qty)
                                logger.info(f"🔢 Hindi number detected: '{text_stripped}' → qty={qty}")
                                confirmation = {'decision': 'yes', 'confidence': 1.0}
                            else:
                                confirmation = await intent_classifier.classify_confirmation(text, shared_state['pending'])
                                
                                # === QUANTITY OVERRIDE: extract number from confirmation text ===
                                # e.g., "haan do packet", "kardo lekin 3", "ok 5 daal do", "haan aadha kilo"
                                if confirmation['decision'] == 'yes':
                                    # Check for Hindi number words in the text
                                    HINDI_QTY_MAP = {
                                        'ek': 1, 'do': 2, 'teen': 3, 'char': 4, 'chaar': 4,
                                        'paanch': 5, 'panch': 5, 'chhah': 6, 'che': 6,
                                        'saat': 7, 'aath': 8, 'nau': 9, 'das': 10,
                                        'aadha': 0.5, 'adha': 0.5, 'dhai': 2.5, 'dedh': 1.5,
                                        'savaa': 1.25, 'paune': 0.75,
                                    }
                                    detected_qty = None
                                    words = text_stripped.split()
                                    
                                    for word in words:
                                        # Check Hindi number words
                                        if word in HINDI_QTY_MAP:
                                            detected_qty = HINDI_QTY_MAP[word]
                                            break
                                        # Check English digits
                                        try:
                                            num = float(word)
                                            if 0 < num <= 100:
                                                detected_qty = num
                                                break
                                        except ValueError:
                                            pass
                                    
                                    if detected_qty is not None:
                                        old_qty = shared_state['pending']['quantity']
                                        shared_state['pending']['quantity'] = float(detected_qty)
                                        logger.info(f"🔢 Quantity override in confirmation: '{text_stripped}' → qty {old_qty} → {detected_qty}")
                            
                            if confirmation['decision'] == 'yes' and confirmation['confidence'] >= 0.6:
                                pending = shared_state['pending']
                                await _execute_cart_action(
                                    pending['action'], pending['product'], pending['quantity'],
                                    websocket, session_cart
                                )
                                shared_state['state'] = ConversationState.IDLE
                                shared_state['pending'] = None
                                
                                # Send TTS confirmation with quantity
                                qty_int = int(pending['quantity']) if pending['quantity'] == int(pending['quantity']) else pending['quantity']
                                if pending['action'] == 'remove':
                                    conf_msg = f"Ji sir, {pending['product']['name']} cart se hata diya"
                                elif pending['action'] == 'update':
                                    conf_msg = f"Ji sir, {pending['product']['name']} ki quantity {qty_int} kar diya"
                                else:
                                    conf_msg = f"Ji sir, {pending['product']['name']} {qty_int} quantity add kar diya"
                                pcm = await generate_sarvam_tts(conf_msg)
                                await websocket.send_text(json.dumps({'event': 'transcript', 'text': conf_msg, 'is_user': False}))
                                if pcm: await websocket.send_bytes(pcm)
                                
                            elif confirmation['decision'] == 'cancel':
                                shared_state['state'] = ConversationState.IDLE
                                shared_state['pending'] = None
                                msg = "Theek hai, cancel"
                                pcm = await generate_sarvam_tts(msg)
                                await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                if pcm: await websocket.send_bytes(pcm)
                                logger.info("🛑 CANCEL in AWAITING_CONFIRM")
                            elif confirmation['decision'] == 'no' and confirmation['confidence'] >= 0.6:
                                shared_state['state'] = ConversationState.IDLE
                                shared_state['pending'] = None
                                msg = "Theek hai, nahi karte"
                                pcm = await generate_sarvam_tts(msg)
                                await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                if pcm: await websocket.send_bytes(pcm)
                                logger.info("❌ Confirmation denied")
                            else:
                                # Re-classify as new intent (pass last product for pronoun resolution like 'isko')
                                last_product_name = None
                                if shared_state.get('pending') and shared_state['pending'].get('product'):
                                    last_product_name = shared_state['pending']['product'].get('name')
                                
                                shared_state['state'] = ConversationState.IDLE
                                shared_state['pending'] = None
                                
                                user_intent = await intent_classifier.classify_user_intent(
                                    text, context_products, session_cart, last_product_name
                                )
                                if user_intent:
                                    action = user_intent['action']
                                    product_name = user_intent['product_name']
                                    brand = user_intent['brand']
                                    quantity = user_intent['quantity'] or 1.0
                                    is_relative = user_intent.get('is_relative', False)
                                    
                                    matches, source_store, needs_approval = await _resolve_products(
                                        product_name, brand, context_products,
                                        shared_state['approved_stores'], current_store_id,
                                        intent_classifier
                                    )
                                    
                                    if len(matches) == 0:
                                        msg = f"Sir, {product_name} available nahi hai"
                                        pcm = await generate_sarvam_tts(msg)
                                        await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                        if pcm: await websocket.send_bytes(pcm)
                                    elif needs_approval:
                                        store_names = {'DEMO_STORE_1': 'TestShop 1', 'DEMO_STORE_2': 'TestShop 2', 'DEMO_STORE_3': 'TestShop 3'}
                                        store_name = store_names.get(source_store, 'other shop')
                                        shared_state['state'] = ConversationState.AWAITING_STORE_APPROVAL
                                        shared_state['pending'] = {'action': action, 'products': matches, 'quantity': quantity, 'source_store_id': source_store, 'product_name': product_name}
                                        cross_msg = f"Sir, {product_name} yahan nahi hai, lekin {store_name} mein available hai. Wahan se add kar dun?"
                                        pcm = await generate_sarvam_tts(cross_msg)
                                        await websocket.send_text(json.dumps({'event': 'transcript', 'text': cross_msg, 'is_user': False}))
                                        if pcm: await websocket.send_bytes(pcm)
                                    elif len(matches) == 1:
                                        product = matches[0]
                                        final_action = 'add' if action == 'query' else action
                                        prod_id = _get_prod_id(product)
                                        current_qty = session_cart.get(prod_id, 0)
                                        
                                        # Compute final quantity for relative updates
                                        final_qty = quantity
                                        if final_action == 'update' and is_relative and current_qty > 0:
                                            final_qty = current_qty + quantity
                                        elif final_action == 'remove':
                                            final_qty = 0
                                        
                                        # AUTO-EXECUTE: user already gave a clear instruction, no need for double confirmation
                                        await _execute_cart_action(final_action, product, final_qty, websocket, session_cart)
                                        qty_int = int(final_qty) if final_qty == int(final_qty) else final_qty
                                        if final_action == 'remove':
                                            conf_msg = f"Ji sir, {product['name']} cart se hata diya"
                                        elif final_action == 'update':
                                            conf_msg = f"Ji sir, {product['name']} ki quantity {qty_int} kar diya"
                                        else:
                                            conf_msg = f"Ji sir, {product['name']} {qty_int} quantity add kar diya"
                                        pcm = await generate_sarvam_tts(conf_msg)
                                        await websocket.send_text(json.dumps({'event': 'transcript', 'text': conf_msg, 'is_user': False}))
                                        if pcm: await websocket.send_bytes(pcm)
                                        logger.info(f"✅ Auto-executed (re-process): {final_action.upper()} {final_qty}x {product['name']}")
                                    else:
                                        final_action = 'add' if action == 'query' else action
                                        in_cart_matches = [p for p in matches if session_cart.get(_get_prod_id(p), 0) > 0]
                                        if final_action in ('update', 'remove') and len(in_cart_matches) == 1:
                                            product = in_cart_matches[0]
                                            prod_id = _get_prod_id(product)
                                            current_qty = session_cart.get(prod_id, 0)
                                            
                                            final_qty = quantity
                                            if final_action == 'update' and is_relative and current_qty > 0:
                                                final_qty = current_qty + quantity
                                            elif final_action == 'remove':
                                                final_qty = 0
                                            
                                            # AUTO-EXECUTE: single in-cart match, clear instruction
                                            await _execute_cart_action(final_action, product, final_qty, websocket, session_cart)
                                            qty_int = int(final_qty) if final_qty == int(final_qty) else final_qty
                                            if final_action == 'remove':
                                                conf_msg = f"Ji sir, {product['name']} cart se hata diya"
                                            else:
                                                conf_msg = f"Ji sir, {product['name']} ki quantity {qty_int} kar diya"
                                            pcm = await generate_sarvam_tts(conf_msg)
                                            await websocket.send_text(json.dumps({'event': 'transcript', 'text': conf_msg, 'is_user': False}))
                                            if pcm: await websocket.send_bytes(pcm)
                                            logger.info(f"✅ Auto-executed (re-process, in-cart): {final_action.upper()} {final_qty}x {product['name']}")
                                        else:
                                            if final_action in ('update', 'remove') and len(in_cart_matches) > 1:
                                                matches = in_cart_matches
                                            shared_state['state'] = ConversationState.AWAITING_SELECTION
                                            shared_state['pending'] = {'action': final_action, 'products': matches, 'quantity': quantity, 'source_store_id': source_store}
                                            options = []
                                            for prod in matches[:5]:
                                                prod_id = _get_prod_id(prod)
                                                options.append({"product_id": prod_id, "name": prod.get('name'), "brand": prod.get('brand'), "price": prod.get('price', 0), "unit": prod.get('weight', prod.get('unit')), "in_cart": int(session_cart.get(prod_id, 0)), "store_id": prod.get('store_id')})
                                            await websocket.send_text(json.dumps({'event': 'product_selection', 'product_name': product_name, 'action': final_action, 'quantity': quantity, 'options': options}))
                                            sel_msg = f"Sir, {len(matches)} varieties available hain. Screen pe dekh lijiye"
                                            pcm = await generate_sarvam_tts(sel_msg)
                                            await websocket.send_text(json.dumps({'event': 'transcript', 'text': sel_msg, 'is_user': False}))
                                            if pcm: await websocket.send_bytes(pcm)
                                
                        elif current_state == ConversationState.AWAITING_SELECTION:
                            # User should tap, but might speak or cancel
                            pending = shared_state['pending']
                            text_lower = text.strip().lower()
                            
                            # Check cancel keywords first
                            if text_lower in CANCEL_KEYWORDS:
                                shared_state['state'] = ConversationState.IDLE
                                shared_state['pending'] = None
                                await websocket.send_text(json.dumps({'event': 'clear_selection'}))
                                msg = "Theek hai"
                                pcm = await generate_sarvam_tts(msg)
                                await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                if pcm: await websocket.send_bytes(pcm)
                                logger.info("🛑 CANCEL in AWAITING_SELECTION")
                                shared_state['processing'] = False
                                continue
                            
                            matches = pending.get('products', [])
                            selected_product = None
                            for prod in matches:
                                if text_lower in prod.get('name', '').lower() or text_lower in prod.get('brand', '').lower():
                                    selected_product = prod
                                    break
                                    
                            if selected_product:
                                await _execute_cart_action(
                                    pending['action'], selected_product, pending['quantity'],
                                    websocket, session_cart
                                )
                                shared_state['state'] = ConversationState.IDLE
                                shared_state['pending'] = None
                                
                                action_word = {'add': 'add', 'update': 'update', 'remove': 'remove'}.get(pending['action'], 'add')
                                qty_int = int(pending['quantity']) if pending['quantity'] == int(pending['quantity']) else pending['quantity']
                                if pending['action'] == 'remove':
                                    conf_text = f"Ji sir, {selected_product['name']} cart se hata diya"
                                elif pending['action'] == 'update':
                                    conf_text = f"Ji sir, {selected_product['name']} ki quantity {qty_int} kar diya"
                                else:
                                    conf_text = f"Ji sir, {selected_product['name']} {qty_int} quantity add kar diya"
                                pcm = await generate_sarvam_tts(conf_text)
                                await websocket.send_text(json.dumps({'event': 'transcript', 'text': conf_text, 'is_user': False}))
                                if pcm: await websocket.send_bytes(pcm)
                            else:
                                # No voice match in selection list — reset to IDLE
                                # and re-process as new intent
                                shared_state['state'] = ConversationState.IDLE
                                shared_state['pending'] = None
                                logger.info(f"🔄 Unrelated speech in AWAITING_SELECTION: '{text}' — re-processing as new intent")
                                
                                # Re-run IDLE logic for this speech
                                user_intent = await intent_classifier.classify_user_intent(
                                    text, context_products, session_cart
                                )
                                if user_intent:
                                    action = user_intent['action']
                                    product_name = user_intent['product_name']
                                    brand = user_intent['brand']
                                    quantity = user_intent['quantity'] or 1.0
                                    
                                    matches, source_store, needs_approval = await _resolve_products(
                                        product_name, brand, context_products,
                                        shared_state['approved_stores'], current_store_id,
                                        intent_classifier
                                    )
                                    
                                    if len(matches) == 0:
                                        msg = f"Sir, {product_name} available nahi hai"
                                        pcm = await generate_sarvam_tts(msg)
                                        await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                        if pcm: await websocket.send_bytes(pcm)
                                    elif needs_approval:
                                        store_names = {'DEMO_STORE_1': 'TestShop 1', 'DEMO_STORE_2': 'TestShop 2', 'DEMO_STORE_3': 'TestShop 3'}
                                        store_name = store_names.get(source_store, 'other shop')
                                        shared_state['state'] = ConversationState.AWAITING_STORE_APPROVAL
                                        shared_state['pending'] = {'action': action, 'products': matches, 'quantity': quantity, 'source_store_id': source_store, 'product_name': product_name}
                                        cross_msg = f"Sir, {product_name} yahan nahi hai, lekin {store_name} mein available hai. Wahan se add kar dun?"
                                        pcm = await generate_sarvam_tts(cross_msg)
                                        await websocket.send_text(json.dumps({'event': 'transcript', 'text': cross_msg, 'is_user': False}))
                                        if pcm: await websocket.send_bytes(pcm)
                                    elif len(matches) == 1:
                                        product = matches[0]
                                        final_action = 'add' if action == 'query' else action
                                        shared_state['state'] = ConversationState.AWAITING_CONFIRM
                                        shared_state['pending'] = {'action': final_action, 'product': product, 'quantity': quantity}
                                        if final_action == 'remove':
                                            conf_msg = f"Sir, {product['name']} cart se hata dun?"
                                        elif final_action == 'update':
                                            conf_msg = f"Sir, {product['name']} ki quantity {int(quantity) if quantity == int(quantity) else quantity} kar dun?"
                                        else:
                                            conf_msg = f"Sir, {product['name']} add karun?"
                                        pcm = await generate_sarvam_tts(conf_msg)
                                        await websocket.send_text(json.dumps({'event': 'transcript', 'text': conf_msg, 'is_user': False}))
                                        if pcm: await websocket.send_bytes(pcm)
                                    else:
                                        final_action = 'add' if action == 'query' else action
                                        shared_state['state'] = ConversationState.AWAITING_SELECTION
                                        shared_state['pending'] = {'action': final_action, 'products': matches, 'quantity': quantity, 'source_store_id': source_store}
                                        options = []
                                        for prod in matches[:5]:
                                            prod_id = _get_prod_id(prod)
                                            options.append({"product_id": prod_id, "name": prod.get('name'), "brand": prod.get('brand'), "price": prod.get('price', 0), "unit": prod.get('weight', prod.get('unit')), "in_cart": int(session_cart.get(prod_id, 0)), "store_id": prod.get('store_id')})
                                        await websocket.send_text(json.dumps({'event': 'product_selection', 'product_name': product_name, 'action': final_action, 'quantity': quantity, 'options': options}))
                                        sel_msg = f"Sir, {len(matches)} varieties available hain. Screen pe dekh lijiye"
                                        pcm = await generate_sarvam_tts(sel_msg)
                                        await websocket.send_text(json.dumps({'event': 'transcript', 'text': sel_msg, 'is_user': False}))
                                        if pcm: await websocket.send_bytes(pcm)
                                
                        elif current_state == ConversationState.AWAITING_CLARIFICATION:
                            pending = shared_state['pending']
                            text_lower_clar = text.strip().lower()
                            
                            # Check cancel keywords first
                            if text_lower_clar in CANCEL_KEYWORDS:
                                shared_state['state'] = ConversationState.IDLE
                                shared_state['pending'] = None
                                msg = "Theek hai"
                                pcm = await generate_sarvam_tts(msg)
                                await websocket.send_text(json.dumps({'event': 'transcript', 'text': msg, 'is_user': False}))
                                if pcm: await websocket.send_bytes(pcm)
                                logger.info("🛑 CANCEL in AWAITING_CLARIFICATION")
                                shared_state['processing'] = False
                                continue
                            
                            existing_intent = await intent_classifier.classify_existing_item_intent(
                                text, pending['product']['name'], pending['current_quantity']
                            )
                            
                            if existing_intent['confidence'] >= 0.6:
                                action = existing_intent['action']
                                quantity = existing_intent.get('quantity')
                                product = pending['product']
                                current_qty = pending['current_quantity']
                                
                                if action == 'add_more':
                                    qty_val = quantity or 1.0
                                    shared_state['state'] = ConversationState.AWAITING_CONFIRM
                                    shared_state['pending'] = {'action': 'add', 'product': product, 'quantity': qty_val}
                                    conf_msg = f"Sir, {product['name']} {int(qty_val) if qty_val == int(qty_val) else qty_val} aur add karun?"
                                    pcm = await generate_sarvam_tts(conf_msg)
                                    await websocket.send_text(json.dumps({'event': 'transcript', 'text': conf_msg, 'is_user': False}))
                                    if pcm: await websocket.send_bytes(pcm)
                                elif action == 'update':
                                    qty_val = quantity or current_qty
                                    shared_state['state'] = ConversationState.AWAITING_CONFIRM
                                    shared_state['pending'] = {'action': 'update', 'product': product, 'quantity': qty_val}
                                    conf_msg = f"Sir, {product['name']} ki quantity {int(qty_val) if qty_val == int(qty_val) else qty_val} kar dun?"
                                    pcm = await generate_sarvam_tts(conf_msg)
                                    await websocket.send_text(json.dumps({'event': 'transcript', 'text': conf_msg, 'is_user': False}))
                                    if pcm: await websocket.send_bytes(pcm)
                                elif action == 'remove':
                                    shared_state['state'] = ConversationState.AWAITING_CONFIRM
                                    shared_state['pending'] = {'action': 'remove', 'product': product, 'quantity': 0}
                                    conf_msg = f"Sir, {product['name']} cart se hata dun?"
                                    pcm = await generate_sarvam_tts(conf_msg)
                                    await websocket.send_text(json.dumps({'event': 'transcript', 'text': conf_msg, 'is_user': False}))
                                    if pcm: await websocket.send_bytes(pcm)


                        shared_state['processing'] = False  # Release processing lock

                    else:
                        # Nova Sonic AI spoke — ALWAYS suppress.
                        # Nova Sonic is used ONLY for transcription (STT).
                        # All responses are generated by our state machine + Sarvam TTS.
                        logger.info(f"🔇 Suppressed Nova Sonic AI: {text[:80]}...")
                            
        except Exception as e:
            logger.error(f"Response forwarding error: {e}")
    
    forward_task = asyncio.create_task(forward_responses())
    
    # Audio streaming
    audio_started = False
    
    try:
        while True:
            data = await websocket.receive()
            
            if 'bytes' in data:
                audio_chunk = data['bytes']
                if not audio_started:
                    await nova_sonic.start_audio_input(session_id)
                    audio_started = True
                await nova_sonic.send_audio_chunk(session_id, audio_chunk)
            
            elif 'text' in data:
                try:
                    message = json.loads(data['text'])
                    if message.get('event') == 'end_audio':
                        if audio_started:
                            await nova_sonic.end_audio_input(session_id)
                            audio_started = False
                    elif message.get('event') == 'start_audio':
                        if not audio_started:
                            await nova_sonic.start_audio_input(session_id)
                            audio_started = True
                    elif message.get('event') == 'product_selected':
                        # User selected a product from the selection UI
                        product_id = message.get('product_id')
                        # Use the quantity from original request stored in pending state
                        # (not Flutter's message, which defaults to 1.0)
                        
                        if shared_state['state'] == ConversationState.AWAITING_SELECTION and shared_state['pending']:
                            # Find the selected product
                            products = shared_state['pending'].get('products', [])
                            selected_quantity = shared_state['pending'].get('quantity', 1.0)
                            selected_product = None
                            for prod in products:
                                if _get_prod_id(prod) == product_id:
                                    selected_product = prod
                                    break
                            
                            if selected_product:
                                # Tapping a product in the UI always means ADD
                                action = shared_state['pending']['action']
                                if action == 'query':
                                    action = 'add'
                                
                                # Use shared helper to execute cart action
                                await _execute_cart_action(
                                    action, selected_product, selected_quantity,
                                    websocket, session_cart
                                )
                                # If cross-store, approve the store for future requests
                                source_store_id = shared_state['pending'].get('source_store_id')
                                if source_store_id:
                                    shared_state['approved_stores'].add(source_store_id)
                                    for p in shared_state['pending'].get('products', []):
                                        if p not in context_products:
                                            context_products.append(p)
                                    logger.info(f"🏪 Approved store {source_store_id}, merged products into context")
                                    
                                shared_state['state'] = ConversationState.IDLE
                                shared_state['pending'] = None
                                
                                # AI confirms the selection — generate TTS first
                                action_word = {'add': 'add', 'update': 'update', 'remove': 'remove'}.get(action, 'add')
                                qty_int = int(selected_quantity) if selected_quantity == int(selected_quantity) else selected_quantity
                                if action == 'remove':
                                    confirmation_text = f"Ji sir, {selected_product['name']} cart se hata diya"
                                elif action == 'update':
                                    confirmation_text = f"Ji sir, {selected_product['name']} ki quantity {qty_int} kar diya"
                                else:
                                    confirmation_text = f"Ji sir, {selected_product['name']} {qty_int} quantity add kar diya"
                                pcm_audio = await generate_sarvam_tts(confirmation_text)
                                
                                # Then send transcript + audio together
                                await websocket.send_text(json.dumps({
                                    'event': 'transcript',
                                    'text': confirmation_text,
                                    'is_user': False
                                }))
                                
                                if pcm_audio:
                                    await websocket.send_bytes(pcm_audio)
                    
                    elif message.get('event') == 'sync_cart':
                        # Sync cart state from Flutter app on session start
                        synced_product_ids = []
                        for item in message.get('items', []):
                            pid = item.get('product_id', '')
                            qty = item.get('quantity', 0)
                            if pid and qty > 0:
                                session_cart[pid] = qty
                                synced_product_ids.append(pid)
                        logger.info(f"🔄 Synced cart from app: {len(session_cart)} items")
                        
                        # Auto-approve stores of synced cart items AND load their full inventory
                        if synced_product_ids:
                            from app.db.mongodb import get_database
                            db = await get_database()
                            from bson import ObjectId
                            
                            # Collect unique cross-store IDs
                            cross_store_ids = set()
                            for pid in synced_product_ids:
                                try:
                                    product = await db.products.find_one({'_id': ObjectId(pid)})
                                    if product and product.get('store_id'):
                                        store_id_val = product['store_id']
                                        if store_id_val != current_store_id:
                                            cross_store_ids.add(store_id_val)
                                except Exception:
                                    pass  # ID format mismatch, skip
                            
                            # Auto-approve each cross-store AND load its full inventory into context
                            for cs_id in cross_store_ids:
                                shared_state['approved_stores'].add(cs_id)
                                logger.info(f"🏪 Auto-approved store {cs_id} (synced cart item)")
                                
                                # Load all products from this store into context_products
                                store_products = await db.products.find({'store_id': cs_id}).to_list(length=100)
                                for p in store_products:
                                    if p not in context_products:
                                        context_products.append(p)
                                logger.info(f"📦 Loaded {len(store_products)} products from {cs_id} into context")
                except json.JSONDecodeError:
                    pass
    except (WebSocketDisconnect, RuntimeError) as e:
        if isinstance(e, RuntimeError) and "Cannot call" not in str(e):
            logger.error(f"Error in customer voice session: {e}")
        else:
            logger.info(f"Customer voice session ended for user: {user_id}")
    except Exception as e:
        logger.error(f"Error in customer voice session: {e}")
    finally:
        if audio_started:
            try:
                await nova_sonic.end_audio_input(session_id)
            except Exception:
                pass
        
        response_task.cancel()
        forward_task.cancel()
        await nova_sonic.close_session(session_id)
        await context_service.cleanup_context(session_id)
        
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/voice/store/{store_id}")
async def store_voice_assistant(websocket: WebSocket, store_id: str):
    """Voice assistant for NukkadStore owners - Inventory management and business insights"""
    await websocket.accept()
    logger.info(f"Store voice session started for store: {store_id}")
    
    nova_sonic = NovaSonicService()
    context_service = VoiceContextService()
    greeting_sent = False  # Track if greeting was sent
    
    # Create session with store management persona and tools
    session = await nova_sonic.create_session(
        user_id=store_id,
        persona="personal_manager",
        tools=["get_sales_report", "get_inventory_status", "get_low_stock_alerts",
               "suggest_pricing", "forecast_demand", "get_revenue_analytics",
               "get_top_products", "get_daily_summary"]
    )
    
    session_id = session['id']
    
    # Initialize store context (inventory, sales data, etc.)
    try:
        context_summary = await context_service.initialize_store_context(
            session_id=session_id, store_id=store_id
        )
        await websocket.send_text(json.dumps({
            'event': 'context_loaded', 'data': context_summary
        }))
        
        # Only send greeting if not sent before
        if not greeting_sent:
            greeting_sent = True
            
            # Wait a moment for Flutter to be ready to receive audio
            await asyncio.sleep(0.1)
            
            # Send greeting message with audio
            greeting_text = "नमस्ते सर! मैं आपका AI assistant हूं। Inventory update, sales check, या कुछ भी पूछिए।"
            await websocket.send_text(json.dumps({
                'event': 'transcript',
                'text': greeting_text,
                'is_user': False
            }))
            
            # Generate and send Sarvam TTS audio for greeting
            pcm_audio = await generate_sarvam_tts(greeting_text)
            if pcm_audio:
                logger.info(f"Sending greeting audio ({len(pcm_audio)} bytes)")
                await websocket.send_bytes(pcm_audio)
            else:
                logger.warning("Failed to generate greeting audio")
            
    except Exception as e:
        logger.error(f"Error loading store context: {str(e)}")
    
    response_queue = asyncio.Queue()
    
    async def process_responses():
        """Process responses from Nova Sonic"""
        try:
            async for response in nova_sonic.receive_responses(session_id):
                await response_queue.put(response)
        except Exception as e:
            logger.error(f"Response processing error: {e}")
            await response_queue.put(None)
    
    response_task = asyncio.create_task(process_responses())
    
    # NOTE: We DON'T send inventory context to Nova Sonic to avoid "Chat history over max limit" error
    # Nova Sonic is only used for STT/TTS, not for understanding inventory queries
    # All inventory queries are handled directly in the text_query handler below
    
    async def forward_responses():
        """Forward responses to frontend - SUPPRESS Nova Sonic AI responses"""
        try:
            while True:
                response = await response_queue.get()
                if response is None:
                    break
                
                if response['type'] == 'audio_output':
                    # Skip Nova Sonic's audio - we use Sarvam TTS instead
                    pass
                elif response['type'] in ('transcript', 'transcription'):
                    is_user = response.get('is_user', False)
                    
                    if is_user:
                        # User spoke - transliterate Hindi to English and process
                        text = response['text']
                        text_transliterated = transliterate_hindi_to_english(text)
                        
                        # Send transliterated transcript to frontend
                        await websocket.send_text(json.dumps({
                            'event': 'transcript',
                            'text': text_transliterated,
                            'is_user': True
                        }))
                        
                        # Process the query directly (like text_query handler)
                        logger.info(f"Processing voice query: {text_transliterated}")
                        
                        from app.db.mongodb import get_database
                        db = await get_database()
                        
                        response_text = ""
                        query_lower = text_transliterated.lower()
                        
                        # Handle different query types
                        if 'stock' in query_lower or 'inventory' in query_lower:
                            products = await db.products.find({'store_id': store_id}).to_list(length=1000)
                            total_products = len(products)
                            in_stock = sum(1 for p in products if p.get('stock_quantity', p.get('stock', 0)) > 0)
                            low_stock = sum(1 for p in products if 0 < p.get('stock_quantity', p.get('stock', 0)) < 10)
                            response_text = f"Sir, aapke paas {total_products} products hain. {in_stock} items stock mein hain, aur {low_stock} items kam stock mein hain."
                            
                        elif 'sales' in query_lower or 'sell' in query_lower or 'order' in query_lower:
                            from datetime import datetime, timedelta
                            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                            orders = await db.orders.find({
                                'store_id': store_id,
                                'created_at': {'$gte': today_start}
                            }).to_list(length=1000)
                            
                            total_sales = sum(order.get('total_amount', 0) for order in orders)
                            order_count = len(orders)
                            response_text = f"Sir, aaj ki sales {int(total_sales)} rupees hai, total {order_count} orders hain."
                            
                        elif 'add' in query_lower and 'stock' in query_lower:
                            response_text = "Sir, stock add karne ke liye product ka naam aur quantity bataiye."
                            
                        elif 'low' in query_lower or 'kam' in query_lower:
                            products = await db.products.find({
                                'store_id': store_id,
                                '$or': [
                                    {'stock': {'$lt': 10, '$gt': 0}},
                                    {'stock_quantity': {'$lt': 10, '$gt': 0}}
                                ]
                            }).to_list(length=10)
                            
                            if products:
                                product_names = [p.get('name', 'Unknown') for p in products[:5]]
                                response_text = f"Sir, ye items kam stock mein hain: {', '.join(product_names)}"
                            else:
                                response_text = "Sir, sab items sufficient stock mein hain."
                        else:
                            response_text = "Sir, main aapki madad kar sakta hoon. Stock check, sales report, ya low stock items ke baare mein poochiye."
                        
                        # Send AI response
                        await websocket.send_text(json.dumps({
                            'event': 'transcript',
                            'text': response_text,
                            'is_user': False
                        }))
                        
                        # Generate and send TTS audio
                        pcm_audio = await generate_sarvam_tts(response_text)
                        if pcm_audio:
                            await websocket.send_bytes(pcm_audio)
                        
                        logger.info(f"Sent response: {response_text[:100]}...")
                    else:
                        # Nova Sonic AI response - SUPPRESS IT
                        logger.info(f"🔇 Suppressed Nova Sonic AI response: {response['text'][:100]}...")
        except Exception as e:
            logger.error(f"Response forwarding error: {e}")
    
    forward_task = asyncio.create_task(forward_responses())
    audio_started = False
    
    try:
        while True:
            data = await websocket.receive()
            
            if 'bytes' in data:
                # Audio chunk from store owner
                if not audio_started:
                    await nova_sonic.start_audio_input(session_id)
                    audio_started = True
                await nova_sonic.send_audio_chunk(session_id, data['bytes'])
                
            elif 'text' in data:
                # Control messages
                try:
                    message = json.loads(data['text'])
                    if message.get('event') == 'end_audio' and audio_started:
                        await nova_sonic.end_audio_input(session_id)
                        audio_started = False
                    elif message.get('event') == 'start_audio' and not audio_started:
                        await nova_sonic.start_audio_input(session_id)
                        audio_started = True
                    elif message.get('event') == 'text_query':
                        # Handle text query from quick action buttons
                        query_text = message.get('text', '')
                        if query_text:
                            logger.info(f"Processing text query: {query_text}")
                            
                            # Echo user query to frontend first
                            await websocket.send_text(json.dumps({
                                'event': 'transcript',
                                'text': query_text,
                                'is_user': True
                            }))
                            
                            # Process the query and generate response
                            from app.db.mongodb import get_database
                            db = await get_database()
                            
                            response_text = ""
                            
                            # Handle different query types
                            if 'stock' in query_text.lower() or 'inventory' in query_text.lower():
                                # Get inventory summary
                                products = await db.products.find({'store_id': store_id}).to_list(length=1000)
                                total_products = len(products)
                                # Check both 'stock' and 'stock_quantity' fields
                                in_stock = sum(1 for p in products if p.get('stock_quantity', p.get('stock', 0)) > 0)
                                low_stock = sum(1 for p in products if 0 < p.get('stock_quantity', p.get('stock', 0)) < 10)
                                response_text = f"Sir, aapke paas {total_products} products hain. {in_stock} items stock mein hain, aur {low_stock} items kam stock mein hain."
                                
                            elif 'sales' in query_text.lower():
                                # Get today's sales
                                from datetime import datetime, timedelta
                                today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                                orders = await db.orders.find({
                                    'store_id': store_id,
                                    'created_at': {'$gte': today_start}
                                }).to_list(length=1000)
                                
                                total_sales = sum(order.get('total_amount', 0) for order in orders)
                                order_count = len(orders)
                                response_text = f"Sir, aaj ki sales {int(total_sales)} rupees hai, total {order_count} orders hain."
                                
                            elif 'add' in query_text.lower() and 'stock' in query_text.lower():
                                response_text = "Sir, stock add karne ke liye product ka naam aur quantity bataiye."
                                
                            elif 'low' in query_text.lower() or 'kam' in query_text.lower():
                                # Get low stock items - check both field names
                                products = await db.products.find({
                                    'store_id': store_id,
                                    '$or': [
                                        {'stock': {'$lt': 10, '$gt': 0}},
                                        {'stock_quantity': {'$lt': 10, '$gt': 0}}
                                    ]
                                }).to_list(length=10)
                                
                                if products:
                                    product_names = [p.get('name', 'Unknown') for p in products[:5]]
                                    response_text = f"Sir, ye items kam stock mein hain: {', '.join(product_names)}"
                                else:
                                    response_text = "Sir, sab items sufficient stock mein hain."
                            else:
                                response_text = "Sir, main aapki madad kar sakta hoon. Stock check, sales report, ya low stock items ke baare mein poochiye."
                            
                            # Send AI response
                            await websocket.send_text(json.dumps({
                                'event': 'transcript',
                                'text': response_text,
                                'is_user': False
                            }))
                            
                            # Generate and send TTS audio
                            pcm_audio = await generate_sarvam_tts(response_text)
                            if pcm_audio:
                                await websocket.send_bytes(pcm_audio)
                            
                            logger.info(f"Sent response: {response_text[:100]}...")
                except json.JSONDecodeError:
                    pass
                    
    except WebSocketDisconnect:
        logger.info(f"Store voice session ended for store: {store_id}")
    except Exception as e:
        logger.error(f"Error in store voice session: {str(e)}")
    finally:
        if audio_started:
            try:
                await nova_sonic.end_audio_input(session_id)
            except Exception:
                pass
        
        response_task.cancel()
        forward_task.cancel()
        await nova_sonic.close_session(session_id)
        await context_service.cleanup_context(session_id)
        
        try:
            await websocket.close()
        except Exception:
            pass
