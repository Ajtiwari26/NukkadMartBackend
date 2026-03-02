"""
Voice Assistant Router - SYNCHRONOUS VERSION (No Race Conditions)
Groq classifies intent → Inject to Nova Sonic → Nova Sonic responds
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.services.nova_sonic_service import NovaSonicService
from app.services.voice_context_service import VoiceContextService
from app.services.intent_classifier import IntentClassifier
import json
import asyncio
import logging
import httpx
import base64
import os

router = APIRouter()
logger = logging.getLogger(__name__)


async def generate_sarvam_tts(text: str) -> bytes | None:
    """Generate high-quality Hindi TTS using Sarvam AI API"""
    url = "https://api.sarvam.ai/text-to-speech"
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        return None

    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": [text],
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


@router.websocket("/ws/voice/customer/{user_id}")
async def customer_voice_assistant(
    websocket: WebSocket,
    user_id: str,
    latitude: float = Query(...),
    longitude: float = Query(...)
):
    """
    SYNCHRONOUS voice assistant - NO RACE CONDITIONS
    Flow: User speaks → Groq classifies → Inject to Sonic → Sonic responds
    """
    await websocket.accept()
    logger.info(f"Customer voice session started for user: {user_id} at ({latitude}, {longitude})")
    
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
    
    # Load context
    try:
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
        
        logger.info(f"Context loaded: {context_summary['stores_count']} stores, {context_summary['products_count']} products")
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
            user_transcript_buffer = None
            pending_action = None  # Store pending action waiting for confirmation
            
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
                        # USER spoke - classify intent BEFORE Nova Sonic responds
                        user_transcript_buffer = text
                        
                        # Forward user transcript immediately
                        await websocket.send_text(json.dumps({
                            'event': 'transcript',
                            'text': text,
                            'is_user': True
                        }))
                        
                        # Classify intent SYNCHRONOUSLY
                        if context_products:
                            user_intent = await intent_classifier.classify_user_intent(
                                text,
                                context_products,
                                session_cart
                            )
                            
                            if user_intent:
                                action = user_intent['action']
                                product_name = user_intent['product_name']
                                brand = user_intent['brand']
                                quantity = user_intent['quantity']
                                matched_products = user_intent['matched_products']
                                
                                # Build JSON context for Nova Sonic
                                context_json = {
                                    "action": action,
                                    "product_name": product_name,
                                    "brand": brand,
                                    "quantity": quantity,
                                    "options": []
                                }
                                
                                # Add product options
                                for prod in matched_products[:5]:  # Max 5 options
                                    prod_id = str(prod.get('id', prod.get('_id', '')))
                                    context_json["options"].append({
                                        "product_id": prod_id,
                                        "name": prod.get('name'),
                                        "brand": prod.get('brand'),
                                        "price": prod.get('price', 0),
                                        "unit": prod.get('weight', prod.get('unit')),
                                        "in_cart": session_cart.get(prod_id, 0)
                                    })
                                
                                # Store pending action for execution after confirmation
                                if action in ['add', 'update', 'remove']:
                                    if len(matched_products) == 1:
                                        # Single product - store for immediate execution
                                        pending_action = {
                                            'action': action,
                                            'product': matched_products[0],
                                            'quantity': quantity if quantity else 1.0
                                        }
                                    else:
                                        # Multiple products - store all options, will select after user clarifies
                                        pending_action = {
                                            'action': action,
                                            'products': matched_products,
                                            'quantity': quantity if quantity else 1.0,
                                            'awaiting_selection': True
                                        }
                                
                                # Inject JSON to Nova Sonic (Sonic decides what to do)
                                instruction = f"USER_INTENT: {json.dumps(context_json, ensure_ascii=False)}"
                                await nova_sonic.inject_instruction(session_id, instruction)
                                
                                logger.info(f"🧠 → Sonic: {action.upper()} {product_name} ({len(matched_products)} options)")
                    
                    else:
                        # AI spoke - check if it's confirming an action
                        ai_text_lower = text.lower()
                        
                        # Detect confirmation phrases
                        confirmation_phrases = ['add kar diya', 'hata diya', 'kar di', 'quantity']
                        is_confirmation = any(phrase in ai_text_lower for phrase in confirmation_phrases)
                        
                        # Execute pending action if AI confirmed
                        if is_confirmation and pending_action:
                            # Check if awaiting product selection
                            if pending_action.get('awaiting_selection'):
                                # User clarified which product - find it from the last user input
                                selected_product = None
                                for prod in pending_action['products']:
                                    prod_name_lower = prod.get('name', '').lower()
                                    # Check if product name mentioned in AI response
                                    if any(word in ai_text_lower for word in prod_name_lower.split()):
                                        selected_product = prod
                                        break
                                
                                if selected_product:
                                    action = pending_action['action']
                                    product = selected_product
                                    quantity = pending_action['quantity']
                                else:
                                    # Couldn't determine product, clear pending
                                    pending_action = None
                                    logger.warning("⚠️ Couldn't determine selected product")
                            else:
                                # Single product case
                                action = pending_action['action']
                                product = pending_action['product']
                                quantity = pending_action['quantity']
                            
                            if pending_action and not pending_action.get('awaiting_selection'):
                                prod_id = str(product.get('id', product.get('_id', '')))
                                store_id = product.get('store_id', '')
                                
                                # Update cart
                                if action == 'add':
                                    session_cart[prod_id] = session_cart.get(prod_id, 0) + quantity
                                elif action == 'update':
                                    session_cart[prod_id] = quantity
                                elif action == 'remove':
                                    session_cart.pop(prod_id, None)
                                
                                # Send to Flutter
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
                                pending_action = None  # Clear pending action
                        
                        # Forward transcript + generate TTS
                        await websocket.send_text(json.dumps({
                            'event': 'transcript',
                            'text': text,
                            'is_user': False
                        }))
                        
                        pcm_audio = await generate_sarvam_tts(text)
                        if pcm_audio:
                            await websocket.send_bytes(pcm_audio)
                            
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
                except json.JSONDecodeError:
                    pass
                
    except WebSocketDisconnect:
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
